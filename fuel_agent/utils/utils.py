#    Copyright 2014 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy
import hashlib
import locale
import math
import os
import random as _random
import re
import shlex
import socket
import string
import subprocess
import time

import jinja2
from oslo_config import cfg
from oslo_log import log as logging
import requests
import six
import stevedore.driver
import urllib3

from fuel_agent import errors

random = _random.SystemRandom()

LOG = logging.getLogger(__name__)

u_opts = [
    cfg.IntOpt(
        'http_max_retries',
        default=30,
        help='Maximum retries count for http requests. 0 means infinite',
    ),
    cfg.FloatOpt(
        'http_request_timeout',
        # Setting it to 10 secs will allow fuel-agent to overcome the momentary
        # peak loads when network bandwidth becomes as low as 0.1MiB/s, thus
        # preventing of wasting too much retries on such false positives.
        default=10.0,
        help='Http request timeout in seconds',
    ),
    cfg.FloatOpt(
        'http_retry_delay',
        default=2.0,
        help='Delay in seconds before the next http request retry',
    ),
    cfg.IntOpt(
        'read_chunk_size',
        default=1048576,
        help='Block size of data to read for calculating checksum',
    ),
    cfg.FloatOpt(
        'execute_retry_delay',
        default=2.0,
        help='Delay in seconds before the next exectuion will retry',
    ),
    cfg.IntOpt(
        'partition_udev_settle_attempts',
        default=10,
        help='How many times udev settle will be called after partitioning'
    ),
]

CONF = cfg.CONF
CONF.register_opts(u_opts)


# NOTE(agordeev): signature compatible with execute from oslo
def execute(*cmd, **kwargs):
    command = ' '.join(cmd)
    LOG.debug('Trying to execute command: %s', command)
    commands = [c.strip() for c in re.split(r'\|', command)]
    if kwargs.get('env_variables'):
        LOG.debug('Env variables: {0}'.
                  format(kwargs.get('env_variables')))
    env = kwargs.pop('env_variables', copy.deepcopy(os.environ))
    env['PATH'] = '/bin:/usr/bin:/sbin:/usr/sbin'
    env['LC_ALL'] = env['LANG'] = env['LANGUAGE'] = kwargs.pop('language', 'C')
    attempts = kwargs.pop('attempts', 1)
    check_exit_code = kwargs.pop('check_exit_code', [0])
    ignore_exit_code = False
    to_filename = kwargs.get('to_filename')
    cwd = kwargs.get('cwd')
    logged = kwargs.pop('logged', False)

    if isinstance(check_exit_code, bool):
        ignore_exit_code = not check_exit_code
        check_exit_code = [0]
    elif isinstance(check_exit_code, int):
        check_exit_code = [check_exit_code]

    to_file = None
    if to_filename:
        to_file = open(to_filename, 'wb')

    for attempt in reversed(six.moves.range(attempts)):
        try:
            process = []
            for c in commands:
                try:
                    # NOTE(eli): Python's shlex implementation doesn't like
                    # unicode. We have to convert to ascii before shlex'ing
                    # the command. http://bugs.python.org/issue6988
                    encoded_command = c.encode('ascii') if six.PY2 else c
                    process.append(subprocess.Popen(
                        shlex.split(encoded_command),
                        env=env,
                        stdin=(process[-1].stdout if process else None),
                        stdout=(to_file
                                if ((len(process) == len(commands) - 1) and
                                    to_file)
                                else subprocess.PIPE),
                        stderr=(subprocess.PIPE),
                        cwd=cwd
                    ))
                except (OSError, ValueError) as e:
                    raise errors.ProcessExecutionError(exit_code=1, stdout='',
                                                       stderr=e, cmd=command)
                if len(process) >= 2:
                    process[-2].stdout.close()
            stdout, stderr = process[-1].communicate()
            if (not ignore_exit_code and
               process[-1].returncode not in check_exit_code):
                    raise errors.ProcessExecutionError(
                        exit_code=process[-1].returncode, stdout=stdout,
                        stderr=stderr, cmd=command)
            if logged:
                LOG.debug('Extended log: \nstdout:{0}\nstderr:{1}'.
                          format(stdout, stderr))
            return (stdout, stderr)
        except errors.ProcessExecutionError as e:
            LOG.warning('Failed to execute command: %s', e)
            if not attempt:
                raise
            else:
                time.sleep(CONF.execute_retry_delay)


def parse_unit(s, unit, ceil=True):
    """Converts '123.1unit' string into ints

    If ceil is True it will be rounded up (124)
    and and down (123) if ceil is False.
    """

    flt = locale.atof(s.split(unit)[0])
    if ceil:
        return int(math.ceil(flt))
    return int(math.floor(flt))


def B2MiB(b, ceil=True):
    if ceil:
        return int(math.ceil(float(b) / 1024 / 1024))
    return int(math.floor(float(b) / 1024 / 1024))


def get_driver(name):
    LOG.debug('Trying to get driver: fuel_agent.drivers.%s', name)
    driver = stevedore.driver.DriverManager(
        namespace='fuel_agent.drivers', name=name).driver
    LOG.debug('Found driver: %s', driver.__name__)
    return driver


def render_and_save(tmpl_dir, tmpl_names, tmpl_data, file_name):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_dir))
    template = env.get_or_select_template(tmpl_names)
    output = template.render(tmpl_data)
    try:
        with open(file_name, 'w') as f:
            f.write(output)
    except Exception:
        raise errors.TemplateWriteError(
            'Something goes wrong while trying to save'
            'templated data to {0}'.format(file_name))


def calculate_md5(filename, size):
    hash = hashlib.md5()
    processed = 0
    with open(filename, "rb") as f:
        while processed < size:
            block = f.read(CONF.read_chunk_size)
            if block:
                block_len = len(block)
                if processed + block_len < size:
                    hash.update(block)
                    processed += block_len
                else:
                    hash.update(block[:size - processed])
                    break
            else:
                break
    return hash.hexdigest()


# TODO(asvechnikov): remove this method when requests lib be able to
#                    to process 'no_proxy'
#                    https://github.com/kennethreitz/requests/issues/2817
def should_bypass_proxy(url, noproxy_addrs):
    """Should url bypass proxy

       Parse hostname from url, check hostname belong to noproxy_addrs

       :param url: url for check
       :param noproxy_addrs: list of ips which should be bypassed
       :return: True if url should bypass proxy, False visa versa
    """
    hostname = six.moves.urllib.parse.urlparse(url).netloc.split(':')[0]

    if noproxy_addrs:
        return hostname in noproxy_addrs

    return False


def init_http_request(url, byte_range=0, proxies=None, noproxy_addrs=None):
    LOG.debug("Trying to initialize http request object %s, byte range: %s",
              url, byte_range)
    if should_bypass_proxy(url, noproxy_addrs):
        LOG.debug("Proxy will be bypassed for url %s", url)
        proxies = None
    retry = 0
    while True:
        if (CONF.http_max_retries == 0) or retry <= CONF.http_max_retries:
            try:
                response_obj = requests.get(
                    url, stream=True,
                    timeout=CONF.http_request_timeout,
                    headers={'Range': 'bytes=%s-' % byte_range},
                    proxies=proxies)
                response_obj.raise_for_status()
            except (socket.timeout,
                    urllib3.exceptions.DecodeError,
                    urllib3.exceptions.ProxyError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.TooManyRedirects,
                    requests.exceptions.HTTPError) as e:
                LOG.debug("Got non-critical error when accessing to %s "
                          "on %s attempt: %s", url, retry + 1, e)
            else:
                LOG.debug("Successful http request to %s on %s retry",
                          url, retry + 1)
                break
            retry += 1
            time.sleep(CONF.http_retry_delay)
        else:
            raise errors.HttpUrlConnectionError(
                "Exceeded maximum http request retries for {url}".format(
                    url=url))
    return response_obj


def makedirs_if_not_exists(path, mode=0o755):
    """Create directory if it does not exist

    :param path: Directory path
    :param mode: Directory mode (Default: 0o755)
    """
    if not os.path.isdir(path):
        os.makedirs(path, mode=mode)


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks"""
    args = [iter(iterable)] * n
    return six.moves.zip_longest(*args, fillvalue=fillvalue)


def guess_filename(path, regexp, sort=True, reverse=True):
    """Tries to find a file by regexp in a given path.

    This method is supposed to be mostly used for looking up
    for available kernel files which are usually 'vmlinuz-X.Y.Z-foo'.
    In order to find the newest one we can sort files in backward
    direction (by default).

    :param path: Directory where to look for a file
    :param regexp: (String) Regular expression (must have python syntax)
    :param sort: (Bool) If True (by default), sort files before looking up.
    It can be necessary when regexp does not unambiguously correspond to file.
    :param reverse: (Bool) If True (by default), sort files
    in backward direction.
    """
    filenames = os.listdir(path)
    if sort:
        filenames = sorted(filenames, reverse=reverse)
    for filename in filenames:
        if re.search(regexp, filename):
            return filename
    return None


def blacklist_udev_rules(udev_rules_dir, udev_rules_lib_dir,
                         udev_rename_substr, udev_empty_rule):
    """Blacklist udev rules

    Here is udev's rules blacklisting to be done:
    by adding symlinks to /dev/null in /etc/udev/rules.d for already
    existent rules in /lib/.
    'parted' generates too many udev events in short period of time
    so we should increase processing speed for those events,
    otherwise partitioning is doomed.
    """
    LOG.debug("Enabling udev's rules blacklisting")
    empty_rule_path = os.path.join(udev_rules_dir,
                                   os.path.basename(udev_empty_rule))
    with open(empty_rule_path, 'w') as f:
        f.write('#\n')
    for rule in os.listdir(udev_rules_lib_dir):
        dst = os.path.join(udev_rules_dir, rule)
        if os.path.isdir(dst):
            continue
        if dst.endswith('.rules'):
            # for successful blacklisting already existent file with name
            # from /etc which overlaps with /lib should be renamed prior
            # symlink creation.
            try:
                if os.path.exists(dst):
                    os.rename(dst, dst[:-len('.rules')] + udev_rename_substr)
                    udevadm_settle()
            except OSError:
                LOG.debug("Skipping udev rule %s blacklising" % dst)
            else:
                os.symlink(empty_rule_path, dst)
                udevadm_settle()
    execute('udevadm', 'control', '--reload-rules', check_exit_code=[0])


def unblacklist_udev_rules(udev_rules_dir, udev_rename_substr):
    """disable udev's rules blacklisting"""
    LOG.debug("Disabling udev's rules blacklisting")
    for rule in os.listdir(udev_rules_dir):
        src = os.path.join(udev_rules_dir, rule)
        if os.path.isdir(src):
            continue
        if src.endswith('.rules'):
            if os.path.islink(src):
                try:
                    os.remove(src)
                    udevadm_settle()
                except OSError:
                    LOG.debug(
                        "Skipping udev rule %s de-blacklisting" % src)
        elif src.endswith(udev_rename_substr):
            try:
                if os.path.exists(src):
                    os.rename(src, src[:-len(udev_rename_substr)] + '.rules')
                    udevadm_settle()
            except OSError:
                LOG.debug("Skipping udev rule %s de-blacklisting" % src)
    execute('udevadm', 'control', '--reload-rules', check_exit_code=[0])
    # NOTE(agordeev): re-create all the links which were skipped by udev
    # while blacklisted
    # NOTE(agordeev): do subsystem match, otherwise it will stuck
    execute('udevadm', 'trigger', '--subsystem-match=block',
            check_exit_code=[0])
    udevadm_settle()


def wait_for_udev_settle(attempts=None):
    """Wait for emptiness of udev queue within attempts*0.1 seconds"""
    attempts = attempts or CONF.partition_udev_settle_attempts
    for attempt in six.moves.range(attempts):
        try:
            udevadm_settle()
        except errors.ProcessExecutionError:
            LOG.warning("udevadm settle did return non-zero exit code. "
                        "Partitioning continues.")
        time.sleep(0.1)


def udevadm_settle():
    execute('udevadm', 'settle', check_exit_code=[0])


def udevadm_trigger_blocks():
    try:
        execute('udevadm', 'trigger', '--subsystem-match=block')
        wait_for_udev_settle()
    except errors.ProcessExecutionError:
        LOG.warning("udevadm trigger did return non-zero exit code. "
                    "Partitioning continues.")


def refresh_multipath():
    # NOTE(kszukielojc): When creating partitions for multipath sometimes
    # symlink without "-part" in /dev/mapper will be generated. To fix that
    # we trigger udev, but this causes both links to coexists. Following calls
    # remove symlinks without "-part".
    execute('dmsetup', 'remove_all')
    execute('multipath', '-F')
    execute('multipath', '-r')
    wait_for_udev_settle()


def parse_kernel_cmdline():
    """Parse linux kernel command line"""
    with open('/proc/cmdline', 'rt') as f:
        cmdline = f.read()
    parameters = {}
    for p in cmdline.split():
        name, _, value = p.partition('=')
        parameters[name] = value
    return parameters


def get_interface_ip(mac_addr):
    """Get IP address of interface with mac_addr"""
    # NOTE(yuriyz): current limitations IPv4 addresses only and one IP per
    # interface.
    ip_pattern = re.compile('inet ([\d\.]+)/')
    out, err = execute('ip', 'addr', 'show', 'scope', 'global')
    lines = out.splitlines()
    for num, line in enumerate(lines):
        if mac_addr in line:
            try:
                ip_line = lines[num + 1]
            except IndexError:
                return
            match = ip_pattern.search(ip_line)
            if match:
                return match.group(1)


def gensalt():
    """Generate SHA-512 salt for crypt.crypt function."""
    letters = string.ascii_letters + string.digits + './'
    sha512prefix = "$6$"
    random_letters = ''.join(random.choice(letters) for _ in range(16))
    return sha512prefix + random_letters

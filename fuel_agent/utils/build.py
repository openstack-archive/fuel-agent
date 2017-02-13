#    Copyright 2015 Mirantis, Inc.
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
import glob
import gzip
import os
import re
import shutil
import signal as sig
import stat
import tempfile
import time
import uuid

from oslo_log import log as logging
import signal
import six
import yaml

from fuel_agent import errors
from fuel_agent.utils import fs as fu
from fuel_agent.utils import hardware as hu
from fuel_agent.utils import utils

LOG = logging.getLogger(__name__)

GRUB2_DMRAID_SETTINGS = 'etc/default/grub.d/dmraid2mdadm.cfg'
DEFAULT_APT_PATH = {
    'sources_file': 'etc/apt/sources.list',
    'sources_dir': 'etc/apt/sources.list.d',
    'preferences_file': 'etc/apt/preferences',
    'preferences_dir': 'etc/apt/preferences.d',
    'conf_dir': 'etc/apt/apt.conf.d',
}
# protocol : conf_file_name
# FIXME(azvyagintsev): Move to oslo_config
# Bug: https://bugs.launchpad.net/fuel/+bug/1514772
PROXY_PROTOCOLS = {
    'ftp': '01fuel_agent-use-proxy-ftp',
    'http': '01fuel_agent-use-proxy-http',
    'https': '01fuel_agent-use-proxy-https'
}
ADDITIONAL_DEBOOTSTRAP_PACKAGES = ['ca-certificates',
                                   'apt-transport-https']


def run_debootstrap(uri, suite, chroot, arch='amd64', eatmydata=False,
                    attempts=10, proxies=None, direct_repo_addr=None):
    """Builds initial base system.

    debootstrap builds initial base system which is capable to run apt-get.
    debootstrap is well known for its glithcy resolving of package dependecies,
    so the rest of packages will be installed later by run_apt_get.
    """
    env_vars = copy.deepcopy(os.environ)
    for proto in six.iterkeys(PROXY_PROTOCOLS):
        if proto in (proxies or {}):
            LOG.debug('Using {0} proxy {1} for debootstrap'.format(
                proto, proxies[proto]))
            env_vars['{0}_proxy'.format(proto)] = proxies[proto]

    if direct_repo_addr:
        env_vars['no_proxy'] = ','.join(direct_repo_addr)
        LOG.debug('Setting no_proxy for: {0}'.format(env_vars['no_proxy']))

    cmds = ['debootstrap',
            '--include={0}'.format(",".join(ADDITIONAL_DEBOOTSTRAP_PACKAGES)),
            '--verbose', '--no-check-gpg',
            '--arch={0}'.format(arch)]
    if eatmydata:
        cmds.extend(['--include=eatmydata'])
    cmds.extend([suite, chroot, uri])
    stdout, stderr = utils.execute(*cmds, attempts=attempts,
                                   env_variables=env_vars)
    LOG.debug('Running deboostrap completed.\nstdout: %s\nstderr: %s', stdout,
              stderr)


def set_apt_get_env():
    # NOTE(agordeev): disable any confirmations/questions from apt-get side
    os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
    os.environ['DEBCONF_NONINTERACTIVE_SEEN'] = 'true'
    os.environ['LC_ALL'] = os.environ['LANG'] = os.environ['LANGUAGE'] = 'C'


def run_apt_get(chroot, packages, eatmydata=False, attempts=10):
    """Runs apt-get install <packages>.

    Unlike debootstrap, apt-get has a perfect package dependecies resolver
    under the hood.
    eatmydata could be used to totally ignore the storm of sync() calls from
    dpkg/apt-get tools. It's dangerous, but could decrease package install
    time in X times.
    """
    for action in ('update', 'dist-upgrade'):
        cmds = ['chroot', chroot, 'apt-get', '-y', action]
        stdout, stderr = utils.execute(*cmds, attempts=attempts)
        LOG.debug('Running apt-get %s completed.\nstdout: %s\nstderr: %s',
                  action, stdout, stderr)
    cmds = ['chroot', chroot, 'apt-get', '-y', 'install', ' '.join(packages)]
    if eatmydata:
        cmds.insert(2, 'eatmydata')
    stdout, stderr = utils.execute(*cmds, attempts=attempts)
    LOG.debug('Running apt-get install completed.\nstdout: %s\nstderr: %s',
              stdout, stderr)


def suppress_services_start(chroot):
    """Suppresses services start.

    Prevents start of any service such as udev/ssh/etc in chrooted environment
    while image is being built.
    """
    path = os.path.join(chroot, 'usr/sbin')
    if not os.path.exists(path):
        os.makedirs(path)
    with open(os.path.join(path, 'policy-rc.d'), 'w') as f:
        f.write('#!/bin/sh\n'
                '# prevent any service from being started\n'
                'exit 101\n')
        os.fchmod(f.fileno(), 0o755)


def clean_dirs(chroot, dirs, delete=False):
    """Removes dirs and recreates them

    :param chroot: Root directory where to look for subdirectories
    :param dirs: List of directories to clean/remove (Relative to chroot)
    :param delete: (Boolean) If True, directories will be removed
    (Default: False)
    """
    for d in dirs:
        path = os.path.join(chroot, d)
        if os.path.isdir(path):
            LOG.debug('Removing dir: %s', path)
            shutil.rmtree(path)
            if not delete:
                LOG.debug('Creating empty dir: %s', path)
                os.makedirs(path)


def remove_files(chroot, files):
    for f in files:
        path = os.path.join(chroot, f)
        if os.path.exists(path):
            os.remove(path)
            LOG.debug('Removed file: %s', path)


def clean_apt_settings(chroot, allow_unsigned_file='allow_unsigned_packages',
                       force_ipv4_file='force_ipv4',
                       pipeline_depth_file='pipeline_depth',
                       install_rule_file='install_rule'):
    """Cleans apt settings such as package sources and repo pinning."""
    files = [DEFAULT_APT_PATH['sources_file'],
             DEFAULT_APT_PATH['preferences_file'],
             os.path.join(DEFAULT_APT_PATH['conf_dir'], force_ipv4_file),
             os.path.join(DEFAULT_APT_PATH['conf_dir'], allow_unsigned_file),
             os.path.join(DEFAULT_APT_PATH['conf_dir'], pipeline_depth_file),
             os.path.join(DEFAULT_APT_PATH['conf_dir'], install_rule_file)]
    # also remove proxies
    for p_file in six.itervalues(PROXY_PROTOCOLS):
        files.append(os.path.join(DEFAULT_APT_PATH['conf_dir'], p_file))
    remove_files(chroot, files)
    dirs = [DEFAULT_APT_PATH['preferences_dir'],
            DEFAULT_APT_PATH['sources_dir']]
    clean_dirs(chroot, dirs)


def fix_cloud_init_config(config_path):
    # NOTE(mzhnichkov): change an order of executing cloud-init modules
    # this change is suitable for cloud-init packages from trust/xenial
    with open(config_path, 'r') as cloud_conf:
        config = yaml.safe_load(cloud_conf)
    if 'write-files' in config['cloud_init_modules']:
        config['cloud_init_modules'].remove('write-files')
    config['cloud_config_modules'].append('write-files')
    with open(config_path, 'w') as cloud_conf:
        yaml.safe_dump(config,
                       cloud_conf, encoding='utf-8', default_flow_style=False)


def do_post_inst(chroot, hashed_root_password,
                 allow_unsigned_file='allow_unsigned_packages',
                 force_ipv4_file='force_ipv4',
                 pipeline_depth_file='pipeline_depth',
                 install_rule_file='install_rule'):
    # NOTE(agordeev): set up password for root
    utils.execute('sed', '-i',
                  's%root:[\*,\!]%root:' + hashed_root_password + '%',
                  os.path.join(chroot, 'etc/shadow'))
    # NOTE(agordeev): backport from bash-script:
    # in order to prevent the later puppet workflow outage, puppet service
    # should be disabled on a node startup.
    # Being enabled by default, sometimes it leads to puppet service hanging
    # and recognizing the deployment as failed.
    # TODO(agordeev): take care of puppet service for other distros, once
    # fuel-agent will be capable of building images for them too.
    if os.path.exists(os.path.join(chroot, 'etc/init.d/puppet')):
        utils.execute('chroot', chroot, 'update-rc.d', 'puppet', 'disable')
    # NOTE(agordeev): disable mcollective to be automatically started on boot
    # to prevent confusing messages in its log (regarding connection errors).
    with open(os.path.join(chroot, 'etc/init/mcollective.override'), 'w') as f:
        f.write("manual\n")
    service_link = os.path.join(
        chroot,
        'etc/systemd/system/multi-user.target.wants/mcollective.service')
    if os.path.exists(service_link):
        os.unlink(service_link)
    cloud_cfg = os.path.join(chroot, 'etc/cloud/cloud.cfg.d/')
    utils.makedirs_if_not_exists(os.path.dirname(cloud_cfg))
    with open(os.path.join(
            chroot,
            'etc/cloud/cloud.cfg.d/99-disable-network-config.cfg'), 'w') as cf:
        yaml.safe_dump({'network': {'config': 'disabled'}}, cf,
                       encoding='utf-8',
                       default_flow_style=False)
    cloud_init_conf = os.path.join(chroot, 'etc/cloud/cloud.cfg')
    if os.path.exists(cloud_init_conf):
        fix_cloud_init_config(cloud_init_conf)
    # NOTE(agordeev): remove custom policy-rc.d which is needed to disable
    # execution of post/pre-install package hooks and start of services
    remove_files(chroot, ['usr/sbin/policy-rc.d'])
    # enable mdadm (remove nomdadmddf nomdadmism options from cmdline)
    utils.execute('chroot', chroot, 'dpkg-divert', '--local', '--add',
                  os.path.join('/', GRUB2_DMRAID_SETTINGS))
    remove_files(chroot, [GRUB2_DMRAID_SETTINGS])
    # remove cached apt files
    utils.execute('chroot', chroot, 'apt-get', 'clean')
    clean_apt_settings(chroot, allow_unsigned_file=allow_unsigned_file,
                       force_ipv4_file=force_ipv4_file,
                       pipeline_depth_file=pipeline_depth_file,
                       install_rule_file=install_rule_file)


def stop_chrooted_processes(chroot, signal=sig.SIGTERM,
                            attempts=10, attempts_delay=2):
    """Sends signal to all processes, which are running inside chroot.

    It tries several times until all processes die. If at some point there
    are no running processes found, it returns True.

    :param chroot: Process root directory.
    :param signal: Which signal to send to processes. It must be either
    SIGTERM or SIGKILL. (Default: SIGTERM)
    :param attempts: Number of attempts (Default: 10)
    :param attempts_delay: Delay between attempts (Default: 2)
    """

    if signal not in (sig.SIGTERM, sig.SIGKILL):
        raise ValueError('Signal must be either SIGTERM or SIGKILL')

    def get_running_processes():
        # fuser shows *some* (mount point, swap file) accesses by
        # the kernel using the string 'kernel' as a pid, ignore these
        out, _ = utils.execute('fuser', '-v', chroot, check_exit_code=False)
        return [pid for pid in out.split() if pid != 'kernel']

    for i in six.moves.range(attempts):
        running_processes = get_running_processes()
        if not running_processes:
            LOG.debug('There are no running processes in %s ', chroot)
            return True
        for p in running_processes:
            try:
                pid = int(p)
                if os.readlink('/proc/%s/root' % pid) == chroot:
                    LOG.debug('Sending %s to chrooted process %s', signal, pid)
                    os.kill(pid, signal)
            except (OSError, ValueError) as e:
                cmdline = ''
                pid = p
                try:
                    with open('/proc/%s/cmdline' % pid) as f:
                        cmdline = f.read()
                except Exception:
                    LOG.debug('Can not read cmdline for pid=%s', pid)
                LOG.warning('Exception while sending signal: '
                            'pid: %s cmdline: %s message: %s. Skipping it.',
                            pid, cmdline, e)

        # First of all, signal delivery is asynchronous.
        # Just because the signal has been sent doesn't
        # mean the kernel will deliver it instantly
        # (the target process might be uninterruptible at the moment).
        # Secondly, exiting might take a while (the process might have
        # some data to fsync, etc)
        LOG.debug('Attempt %s. Waiting for %s seconds', i + 1, attempts_delay)
        time.sleep(attempts_delay)

    running_processes = get_running_processes()
    if running_processes:
        for pid in running_processes:
            cmdline = ''
            try:
                with open('/proc/%s/cmdline' % pid) as f:
                    cmdline = f.read()
            except Exception:
                LOG.debug('Can not read cmdline for pid=%s', pid)
            LOG.warning('Process is still running: pid=%s cmdline: %s',
                        pid, cmdline)
        return False
    return True


def get_free_loop_device(loop_device_major_number=7,
                         max_loop_devices_count=255):
    """Returns the name of free loop device.

    It should return the name of free loop device or raise an exception.
    Unfortunately, free loop device couldn't be reversed for the later usage,
    so we must start to use it as fast as we can.
    If there's no free loop it will try to create new one and ask a system for
    free loop again.
    """
    for minor in range(0, max_loop_devices_count):
        cur_loop = "/dev/loop%s" % minor
        if not os.path.exists(cur_loop):
            os.mknod(cur_loop, 0o660 | stat.S_IFBLK,
                     os.makedev(loop_device_major_number, minor))
        try:
            return utils.execute('losetup', '--find')[0].split()[0]
        except (IndexError, errors.ProcessExecutionError):
            LOG.debug("Couldn't find free loop device, trying again")
    raise errors.NoFreeLoopDevices('Free loop device not found')


def populate_basic_dev(chroot):
    """Populates /dev with basic files, links, device nodes."""
    # prevent failures related with /dev/fd/62
    utils.execute('chroot', chroot, 'rm', '-fr', '/dev/fd')
    utils.execute('chroot', chroot,
                  'ln', '-s', '/proc/self/fd', '/dev/fd')


def create_sparse_tmp_file(dir, suffix, size=8192):
    """Creates sparse file.

    Creates file which consumes disk space more efficiently when the file
    itself is mostly empty.
    """
    tf = tempfile.NamedTemporaryFile(dir=dir, suffix=suffix, delete=False)
    utils.execute('truncate', '-s', '%sM' % size, tf.name)
    return tf.name


def attach_file_to_loop(filename, loop):
    utils.execute('losetup', loop, filename)


def deattach_loop(loop, check_exit_code=[0]):
    LOG.debug('Trying to figure out if loop device %s is attached', loop)
    output = utils.execute('losetup', '-a')[0]
    for line in output.split('\n'):
        # output lines are assumed to have the following format
        # /dev/loop0: [fd03]:130820 (/dev/loop0)
        if loop == line.split(':')[0]:
            LOG.debug('Loop device %s seems to be attached. '
                      'Trying to detach.', loop)
            utils.execute('losetup', '-d', loop,
                          check_exit_code=check_exit_code)


def shrink_sparse_file(filename):
    """Shrinks file to its size of actual data. Only ext fs are supported."""
    utils.execute('e2fsck', '-y', '-f', filename)
    utils.execute('resize2fs', '-M', filename)
    data = hu.parse_simple_kv('dumpe2fs', filename)
    block_count = int(data['block count'])
    block_size = int(data['block size'])
    with open(filename, 'rwb+') as f:
        f.truncate(block_count * block_size)


def strip_filename(name):
    """Strips filename for apt settings.

    The name could only contain alphanumeric, hyphen (-), underscore (_) and
    period (.) characters.
    """
    return re.sub(r"[^a-zA-Z0-9-_.]*", "", name)


def get_release_file(uri, suite, section, proxies=None,
                     direct_repo_addrs=None):
    """Download and parse repo's Release file

    Returns an apt preferences for specified repo.

    :param proxies: Dict protocol:uri format
    :param direct_repo_addrs: List of addresses which should be bypassed
                              by proxy
    :returns: a string with apt preferences rules
    """
    if section:
        # We can't use urljoin here because it works pretty bad in
        # cases when 'uri' doesn't have a trailing slash.
        download_uri = os.path.join(uri, 'dists', suite, 'Release')
    else:
        # Well, we have a flat repo case, so we should download Release
        # file from a different place. Please note, we have to strip
        # a leading slash from suite because otherwise the download
        # link will be wrong.
        download_uri = os.path.join(uri, suite.lstrip('/'), 'Release')

    return utils.init_http_request(download_uri, proxies=proxies,
                                   noproxy_addrs=direct_repo_addrs).text


def parse_release_file(content):
    """Parse Debian repo's Release file content.

    :param content: a Debian's Release file content
    :returns: a dict with repo's attributes
    """
    _multivalued_fields = {
        'SHA1': ['sha1', 'size', 'name'],
        'SHA256': ['sha256', 'size', 'name'],
        'SHA512': ['sha512', 'size', 'name'],
        'MD5Sum': ['md5sum', 'size', 'name'],
    }

    # debian data format is very similiar to yaml, except
    # multivalued field. so we can parse it just like yaml
    # and then perform additional transformation for those
    # fields (we know which ones are multivalues).
    data = yaml.load(content)

    for attr, columns in six.iteritems(_multivalued_fields):
        if attr not in data:
            continue

        values = data[attr].split()
        data[attr] = []

        for group in utils.grouper(values, len(columns)):
            data[attr].append(dict(zip(columns, group)))

    return data


def add_apt_source(name, uri, suite, section, chroot):
    # NOTE(agordeev): The files have either no or "list" as filename extension
    filename = 'fuel-image-{name}.list'.format(name=strip_filename(name))
    if section:
        entry = 'deb {uri} {suite} {section}\n'.format(uri=uri, suite=suite,
                                                       section=section)
    else:
        entry = 'deb {uri} {suite}\n'.format(uri=uri, suite=suite)
    with open(os.path.join(chroot, DEFAULT_APT_PATH['sources_dir'], filename),
              'w') as f:
        f.write(entry)


def add_apt_preference(name, priority, suite, section, chroot, uri,
                       proxies=None, direct_repo_addrs=None):
    """Add apt reference file for the repo

    :param proxies: dict with protocol:uri format
    :param direct_repo_addrs: list of addressess which should be bypassed
                              by proxy
    """

    # NOTE(agordeev): The files have either no or "pref" as filename extension
    filename = 'fuel-image-{name}.pref'.format(name=strip_filename(name))
    # NOTE(agordeev): priotity=None means that there's no specific pinning for
    # particular repo and nothing to process.
    # Default system-wide preferences (priority=500) will be used instead.

    _transformations = {
        'Archive': 'a',
        'Suite': 'a',       # suite is a synonym for archive
        'Codename': 'n',
        'Version': 'v',
        'Origin': 'o',
        'Label': 'l',
    }

    try:
        deb_release = parse_release_file(get_release_file(
            uri, suite, section, proxies=proxies,
            direct_repo_addrs=direct_repo_addrs))
    except ValueError as exc:
        LOG.error(
            "[Attention] Failed to fetch Release file "
            "for repo '{0}': {1} - skipping. "
            "This may lead both to trouble with packages "
            "and broken OS".format(name, six.text_type(exc))
        )
        return

    conditions = set()
    for field, condition in six.iteritems(_transformations):
        if field in deb_release:
            conditions.add(
                '{0}={1}'.format(condition, deb_release[field])
            )

    with open(os.path.join(chroot, DEFAULT_APT_PATH['preferences_dir'],
                           filename), 'w') as f:
        f.write('Package: *\n')
        f.write('Pin: release ')
        f.write(', '.join(conditions) + "\n")
        f.write('Pin-Priority: {priority}\n'.format(priority=priority))


def set_apt_proxy(chroot, proxies, direct_repo_addr=None):
    """Configure proxy for apt-config

    direct_repo_addr:: direct apt address:
    access to it bypass proxies.
    """

    for protocol in six.iterkeys(proxies):
        with open(os.path.join(chroot, DEFAULT_APT_PATH['conf_dir'],
                               PROXY_PROTOCOLS[protocol]), 'w') as f:
                f.write('Acquire::{0}::proxy "{1}";\n'
                        ''.format(protocol, proxies[protocol]))
                LOG.debug('Apply apt-proxy: \nprotocol: {0}\nurl: {1}'
                          ''.format(protocol, proxies[protocol]))
                if direct_repo_addr:
                    for addr in direct_repo_addr:
                        f.write('Acquire::{0}::proxy::{1} "DIRECT";\n'
                                ''.format(protocol, addr))
                        LOG.debug('Set DIRECT repo: \nprotocol:'
                                  ' {0}\nurl: {1}'.format(protocol, addr))


def pre_apt_get(chroot, allow_unsigned_file='allow_unsigned_packages',
                force_ipv4_file='force_ipv4',
                pipeline_depth_file='pipeline_depth',
                install_rule_file='install_rule',
                proxies=None, direct_repo_addr=None):
    """It must be called prior run_apt_get."""
    clean_apt_settings(chroot, allow_unsigned_file=allow_unsigned_file,
                       force_ipv4_file=force_ipv4_file,
                       pipeline_depth_file=pipeline_depth_file,
                       install_rule_file=install_rule_file)
    # NOTE(agordeev): allow to install packages without gpg digest
    with open(os.path.join(chroot, DEFAULT_APT_PATH['conf_dir'],
                           allow_unsigned_file), 'w') as f:
        f.write('APT::Get::AllowUnauthenticated 1;\n')
    with open(os.path.join(chroot, DEFAULT_APT_PATH['conf_dir'],
                           force_ipv4_file), 'w') as f:
        f.write('Acquire::ForceIPv4 "true";\n')
    with open(os.path.join(chroot, DEFAULT_APT_PATH['conf_dir'],
                           pipeline_depth_file), 'w') as f:
        f.write('Acquire::http::Pipeline-Depth 0;\n')
    with open(os.path.join(chroot, DEFAULT_APT_PATH['conf_dir'],
                           install_rule_file), 'w') as f:
        f.write('APT::Install-Recommends "false";\n')
    with open(os.path.join(chroot, DEFAULT_APT_PATH['conf_dir'],
                           install_rule_file), 'a') as f:
        f.write('APT::Install-Suggests "false";\n')
    if proxies:
        set_apt_proxy(chroot, proxies, direct_repo_addr)


def containerize(filename, container, chunk_size=1048576):
    if container == 'gzip':
        output_file = filename + '.gz'
        with open(filename, 'rb') as f:
            # NOTE(agordeev): gzip in python2.6 doesn't have context manager
            # support
            g = gzip.open(output_file, 'wb')
            for chunk in iter(lambda: f.read(chunk_size), ''):
                g.write(chunk)
            g.close()
        os.remove(filename)
        return output_file
    raise errors.WrongImageDataError(
        'Error while image initialization: '
        'unsupported image container: {container}'.format(container=container))


def attach_file_to_free_loop_device(filename, max_loop_devices_count=255,
                                    loop_device_major_number=7,
                                    max_attempts=1):
    """Find free loop device and try to attach `filename` to it.

    If attaching fails then retry again. Max allowed attempts is
    `max_attempts`.

    Returns loop device to which file is attached. Otherwise, raises
    errors.NoFreeLoopDevices.
    """
    loop_device = None
    for i in range(0, max_attempts):
        try:
            LOG.debug('Looking for a free loop device')
            loop_device = get_free_loop_device(
                loop_device_major_number=loop_device_major_number,
                max_loop_devices_count=max_loop_devices_count)

            log_msg = "Attaching image file '{0}' to free loop device '{1}'"
            LOG.debug(log_msg.format(filename, loop_device))
            attach_file_to_loop(filename, loop_device)
            break
        except errors.ProcessExecutionError:
            log_msg = "Couldn't attach image file '{0}' to loop device '{1}'."
            LOG.debug(log_msg.format(filename, loop_device))

            if i == max_attempts - 1:
                log_msg = ("Maximum allowed attempts ({0}) to attach image "
                           "file '{1}' to loop device '{2}' is exceeded.")
                LOG.debug(log_msg.format(max_attempts, filename, loop_device))
                raise errors.NoFreeLoopDevices('Free loop device not found.')
            else:
                log_msg = ("Trying again to attach image file '{0}' "
                           "to free loop device '{1}'. "
                           "Attempt #{2} out of {3}")
                LOG.debug(log_msg.format(filename, loop_device,
                                         i + 1, max_attempts))

    return loop_device


def make_targz(source_dir, output_name=None):
    """Archive the given directory

    :param source_dir: directory to archive
    :param output_name: output file name, might be a relative
    or an absolute path
     """
    if not output_name:
        output_name = six.text_type(uuid.uuid4()) + '.tar.gz'
    utils.makedirs_if_not_exists(os.path.dirname(output_name))

    LOG.info('Creating archive: %s', output_name)
    utils.execute('tar', '-czf', output_name, '--directory',
                  os.path.normcase(source_dir), '.', logged=True)
    return output_name


def run_script_in_chroot(chroot, script):
    """Run script inside chroot

    1)Copy script file inside chroot
    2)Make it executable
    3)Run it with bash
    """
    LOG.info('Copy user-script {0} into chroot:{1}'.format(script, chroot))
    if not os.path.isdir(chroot):
        raise errors.IncorrectChroot(
            "Can't run script in incorrect chroot %s", chroot)
    chrooted_file = os.path.join(chroot, os.path.basename(script))
    shutil.copy(script, chrooted_file)
    LOG.info('Make user-script {0} executable:'.format(chrooted_file))
    os.chmod(chrooted_file, 0o755)
    utils.execute(
        'chroot', chroot, '/bin/bash', '-c', os.path.join(
            '/', os.path.basename(script)), logged=True)
    LOG.debug('User-script completed')


def recompress_initramfs(chroot, compress='xz', initrd_mask='initrd*'):
    """Remove old and rebuild initrd

    :param chroot:
    :param compress: compression type for initrd
    :return:
    :initrd_mask: search kernel file by Unix style pathname
    """
    env_vars = copy.deepcopy(os.environ)
    add_env_vars = {'TMPDIR': '/tmp',
                    'TMP': '/tmp'}

    LOG.debug('Changing initramfs compression type to: %s', compress)
    utils.execute(
        'sed', '-i', 's/^COMPRESS=.*/COMPRESS={0}/'.format(compress),
        os.path.join(chroot, 'etc/initramfs-tools/initramfs.conf'))

    boot_dir = os.path.join(chroot, 'boot')
    initrds = glob.glob(os.path.join(boot_dir, initrd_mask))
    LOG.debug('Removing initrd images: %s', initrds)
    remove_files('/', initrds)

    env_vars.update(add_env_vars)
    LOG.info('Building initramfs')
    cmds = ['chroot', chroot, 'update-initramfs -v -c -k all']
    utils.execute(*cmds,
                  env_variables=env_vars, logged=True)
    LOG.debug('Running "update-initramfs" completed')


def propagate_host_resolv_conf(chroot):
    """Copy DNS settings from host system to chroot.

    Make a backup of original /etc/resolv.conf and /etc/hosts.

    # In case user pass some custom rules in hosts\resolv.conf.
    opposite to restore_resolv_conf
    """
    c_etc = os.path.join(chroot, 'etc/')
    utils.makedirs_if_not_exists(c_etc)
    for conf_name in ('resolv.conf', 'hosts'):
        dst_conf_name = os.path.join(c_etc, conf_name)
        src_conf_name = os.path.join('/etc/', conf_name)
        files_to_copy = [(dst_conf_name, dst_conf_name + '.bak'),
                         (src_conf_name, dst_conf_name)]
        for src, dst in files_to_copy:
            if os.path.isfile(src):
                shutil.copy(src, dst)


def restore_resolv_conf(chroot):
    """Restore hosts/resolv files in chroot

    opposite to propagate_host_resolv_conf
    """
    c_etc = os.path.join(chroot, 'etc/')
    utils.makedirs_if_not_exists(c_etc)
    for conf_name in ('resolv.conf', 'hosts'):
        dst_conf_name = os.path.join(c_etc, conf_name)
        if os.path.isfile(dst_conf_name + '.bak'):
            LOG.debug('Restoring default %s inside chroot', conf_name)
            shutil.move(dst_conf_name + '.bak', dst_conf_name)


def mkdtemp_smart(root_dir, suffix):
    """Create a unique temporary directory in root_dir

     Automatically creates root_dir if it does not exist.
    Otherwise same as tempfile.mkdtemp
    """

    LOG.debug('Creating temporary chroot directory')
    utils.makedirs_if_not_exists(root_dir)
    chroot = tempfile.mkdtemp(
        dir=root_dir, suffix=suffix)
    LOG.debug('Temporary chroot dir: %s', chroot)
    return chroot


def copy_kernel_initramfs(chroot, dstdir, clean=False):
    """Copy latest or newest vmlinuz and initrd from chroot

    :param chroot:
    :param dstdir: copy to folder
    :param clean: remove all vmlinuz\initrd after done
    :return:
    """
    # TODO(azvyagintsev) fetch from uri driver
    # module* : result filename
    files = {'vmlinuz': 'vmlinuz',
             'initrd': 'initrd.img'
             }
    utils.makedirs_if_not_exists(dstdir)
    boot_dir = os.path.join(chroot, 'boot')
    for module in six.iterkeys(files):
        mask = os.path.join(boot_dir, module + '*')
        all_files = glob.glob(mask)
        if len(all_files) > 1:
            raise errors.TooManyKernels(
                "Too many %s detected :%s", module, all_files)
        file_to_copy = all_files[0]
        copy_to = os.path.join(dstdir, files[module])
        LOG.debug('Copying file: %s to: %s', file_to_copy, copy_to)
        shutil.copy(file_to_copy, copy_to)
        if clean:
            files_to_remove = glob.glob(mask)
            remove_files('/', files_to_remove)


def run_mksquashfs(chroot, output_name=None, compression_algorithm='xz'):
    """Pack the target system as squashfs using mksquashfs

    :param chroot: chroot system, to be squashfs'd
    :param output_name: output file name, might be a relative
     or an absolute path

    The kernel squashfs driver has to match with the user space squasfs tools.
    Use the mksquashfs provided by the target distro to achieve this.
    (typically the distro maintainers are smart enough to ship the correct
    version of mksquashfs)
    Use mksquashfs installed in the target system

    1)Mount tmpfs under chroot/mnt
    2)run mksquashfs inside a chroot
    3)move result files to dstdir
    """
    if not output_name:
        output_name = 'root.squashfs' + six.text_type(uuid.uuid4())
    utils.makedirs_if_not_exists(os.path.dirname(output_name))
    dstdir = os.path.dirname(output_name)
    temp = '.mksquashfs.tmp.' + six.text_type(uuid.uuid4())
    s_dst = os.path.join(chroot, 'mnt/dst')
    s_src = os.path.join(chroot, 'mnt/src')
    try:
        fu.mount_fs(
            'tmpfs', 'mnt_{0}'.format(temp),
            (os.path.join(chroot, 'mnt')),
            'rw,nodev,nosuid,noatime,mode=0755,size=4M')
        utils.makedirs_if_not_exists(s_src)
        utils.makedirs_if_not_exists(s_dst)
        # Bind mount the chroot to avoid including various temporary/virtual
        # files (/proc, /sys, /dev, and so on) into the image
        fu.mount_fs(None, chroot, s_src, opts='bind')
        fu.mount_fs(None, None, s_src, 'remount,bind,ro')
        fu.mount_fs(None, dstdir, s_dst, opts='bind')
        # run mksquashfs
        chroot_squash = os.path.join('/mnt/dst/' + temp)
        long_squash = os.path.join(chroot, 'mnt/dst/{0}'.format(temp))
        LOG.info('Building squashfs')
        utils.execute(
            'chroot', chroot, 'mksquashfs', '/mnt/src',
            chroot_squash,
            '-comp', compression_algorithm,
            '-no-progress', '-noappend', logged=True)
        # move to result name
        LOG.debug('Moving file: %s to: %s', long_squash, output_name)
        shutil.move(long_squash, output_name)
    except Exception as exc:
        LOG.error('squashfs_image build failed: %s', exc)
        raise
    finally:
        LOG.info('squashfs_image clean-up')
        stop_chrooted_processes(chroot, signal=signal.SIGTERM)
        fu.umount_fs(os.path.join(chroot, 'mnt/dst'))
        fu.umount_fs(os.path.join(chroot, 'mnt/src'))
        fu.umount_fs(os.path.join(chroot, 'mnt'))


def get_installed_packages(chroot):
    """The packages installed in chroot along with their versions"""

    out, err = utils.execute('chroot', chroot, 'dpkg-query', '-W',
                             '-f="${Package} ${Version};;"')
    pkglist = filter(None, out.split(';;'))
    return dict([pkgver.split() for pkgver in pkglist])


def rsync_inject(src, dst):
    """Recursively copy the src to dst using full source paths

    Example: suppose the source directory looks like
    src/etc/myconfig
    src/usr/bin/myscript

    rsync_inject('src', '/tmp/chroot')

    copies src/etc/myconfig to /tmp/chroot/etc/myconfig,
    and src/usr/bin/myscript to /tmp/chroot/usr/bin/myscript,
    respectively

    """
    utils.makedirs_if_not_exists(os.path.dirname(dst))
    LOG.debug('Rsync files from %s to: %s', src, dst)
    utils.execute('rsync', '-rlptDKv', src + '/',
                  dst + '/', logged=True)


def copy_update_certs(certs, chroot):
    """Try to copy and update CA certificates in chroot"""
    for cert in certs:
        rsync_inject(cert, chroot)
    utils.execute('chroot', chroot, 'update-ca-certificates',
                  check_exit_code=False, logged=True)


def dump_runtime_uuid(uuid, config):
    """Save  runtime_uuid into yaml file

    Simple uuid variable to identify bootstrap.
    Variable will be hard-coded into config yaml file, in build-time
    :param uuid:
    :param config: yaml file
    :return:
    """
    data = {}
    utils.makedirs_if_not_exists(os.path.dirname(config))
    if os.path.isfile(config):
        with open(config, 'r') as f:
            data = yaml.load(f)
    data['runtime_uuid'] = uuid
    LOG.debug('Save runtime_uuid:%s to file: %s', uuid, config)
    with open(config, 'wt') as f:
        yaml.safe_dump(data, stream=f, encoding='utf-8')


def save_bs_container(output, input_dir, format="tar.gz"):
    """Copy files from dir to archive or another directory

    :param output:
    :param input_dir:
    :param format:
    :return:
    """

    if format == 'directory':
        utils.makedirs_if_not_exists(output)
        bs_files = os.listdir(input_dir)
        LOG.debug("Output folder: %s\ntry to copy bootstrap files: %s",
                  output, bs_files)
        for bs_file in bs_files:
            abs_bs_file = os.path.join(input_dir, bs_file)
            if (os.path.isfile(abs_bs_file)):
                if os.path.isfile(os.path.join(output, bs_file)):
                    raise errors.BootstrapFileAlreadyExists(
                        "File: {0} already exists in: {1}"
                        .format(bs_file, output))
                shutil.copy(abs_bs_file, output)
                os.chmod(os.path.join(output, bs_file), 0o755)
        return output
    elif format == 'tar.gz':
        LOG.debug("Try to make output archive file: %s", output)
        output = make_targz(input_dir, output_name=output)
        return output
    else:
        raise errors.WrongOutputContainer(
            "Unsupported bootstrap container format {0}."
            .format(format))


# NOTE(sslypushenko) Modern lvm supports lvmlocal.conf to selective overriding
# set of configuration options. So, this functionality for patching lvm
# configuration should be removed after lvm upgrade in Ubuntu repositories and
# replaced with proper lvmlocal.conf file
def get_lvm_config_value(chroot, section, name):
    """Get option value from current lvm configuration.

    If option is not present in lvm.conf, None returns
    """
    raw_value = utils.execute('chroot', chroot, 'lvm dumpconfig',
                              '/'.join((section, name)),
                              check_exit_code=[0, 5])[0]
    if '=' not in raw_value:
        return

    raw_value = raw_value.split('=')[1].strip()

    re_str = '"[^"]*"'
    re_float = '\\d*\\.\\d*'
    re_int = '\\d+'
    tokens = re.findall('|'.join((re_str, re_float, re_int)), raw_value)

    values = []
    for token in tokens:
        if re.match(re_str, token):
            values.append(token.strip('"'))
        elif re.match(re_float, token):
            values.append(float(token))
        elif re.match(re_int, token):
            values.append(int(token))

    if not values:
        return
    elif len(values) == 1:
        return values[0]
    else:
        return values


def _update_option_in_lvm_raw_config(section, name, value, raw_config):
    """Update option in dumped LVM configuration.

    :param raw_config should be a string with dumped LVM configuration.

    If section and key present in config, option will be overwritten.
    If there is no key but section presents in config, option will be added
    in to the end of section.
    If there are no section and key in config, section will be added in the end
    of the config.
    """
    def dump_value(value):
        if isinstance(value, int):
            return str(value)
        elif isinstance(value, float):
            return '{:.10f}'.format(value).rstrip('0')
        elif isinstance(value, str):
            return '"{}"'.format(value)
        elif isinstance(value, list or tuple):
            return '[{}]'.format(', '.join(dump_value(v) for v in value))

    lines = raw_config.splitlines()
    section_start = next((n for n, line in enumerate(lines)
                          if line.strip().startswith('{} '.format(section))),
                         None)
    if section_start is None:
        raw_section = '{} {{\n\t{}={}\n}}'.format(section, name,
                                                  dump_value(value))
        lines.append(raw_section)
        return '\n'.join(lines)

    line_no = section_start
    while not lines[line_no].strip().endswith('}'):
        if lines[line_no].strip().startswith(name):
            lines[line_no] = '\t{}={}'.format(name, dump_value(value))
            return '\n'.join(lines)
        line_no += 1

    lines[line_no] = '\t{}={}\n}}'.format(name, dump_value(value))
    return '\n'.join(lines)


def override_lvm_config_value(chroot, section, name, value, lvm_conf_file):
    """Override option in LVM configuration.

    If option is not valid, then errors.ProcessExecutionError will be raised
    and lvm configuration will remain unchanged
    """
    lvm_conf_file = os.path.join(chroot, lvm_conf_file.lstrip('/'))
    updated_config = _update_option_in_lvm_raw_config(
        section, name, value,
        utils.execute('chroot', chroot, 'lvm dumpconfig')[0])
    lvm_conf_file_bak = '{}.bak.{}'.format(lvm_conf_file,
                                           time.strftime("%Y_%m_%d_%H_%M_%S"))
    shutil.copy(lvm_conf_file, lvm_conf_file_bak)
    LOG.debug('Backup for origin LVM configuration file: {}'
              ''.format(lvm_conf_file_bak))
    with open(lvm_conf_file, mode='w') as lvm_conf:
        lvm_conf.write(updated_config)

    # NOTE(sslypushenko) Extra cycle of dump/save lvm.conf is required to be
    # sure that updated configuration is valid and to adjust it to general
    # lvm.conf formatting
    try:
        current_config = utils.execute('chroot', chroot, 'lvm dumpconfig')[0]
        with open(lvm_conf_file, mode='w') as lvm_conf:
            lvm_conf.write(current_config)
        LOG.info('LVM configuration {} updated. '
                 'Option {}/{} gets new value: {}'
                 ''.format(lvm_conf_file, section, name, value))
    except errors.ProcessExecutionError as exc:
        shutil.move(lvm_conf_file_bak, lvm_conf_file)
        LOG.debug('Option {}/{} can not be updated with value {}. '
                  'Configuration restored'.format(section, name, value))
        raise exc


def override_lvm_config(chroot, config, lvm_conf_path='/etc/lvm/lvm.conf',
                        update_initramfs=False):
    """Override custom values in LVM configuration

    :param config: should be a dict with part of LVM configuration to override
    Example:
    {'devices': {'filter': ['a/.*/'],
                 'preferred_names': '^/dev/mapper/'}}
    """

    for section in config:
        for name in config[section]:
            override_lvm_config_value(chroot, section, name,
                                      config[section][name],
                                      lvm_conf_path)
    if update_initramfs:
        # NOTE(sslypushenko) We need to update initramfs for pushing
        # LVM configuration into it.
        LOG.info('Updating target initramfs')
        utils.execute('chroot', chroot, 'update-initramfs -v -u -k all')
        LOG.debug('Running "update-initramfs" completed')

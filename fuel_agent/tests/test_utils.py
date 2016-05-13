# Copyright 2011 Justin Santa Barbara
# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import socket

from oslo_config import cfg
import requests
import six
import stevedore
import unittest2
import urllib3

from fuel_agent import errors
from fuel_agent.utils import utils

if six.PY2:
    import mock
elif six.PY3:
    from unittest import mock

CONF = cfg.CONF

_LO_DEVICE = """lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state \
UNKNOWN group default
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
"""

_ETH_DEVICE_NO_IP = """eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc \
pfifo_fast state UP group default qlen 1000
    link/ether 08:60:6e:6f:7d:a5 brd ff:ff:ff:ff:ff:ff
"""

_ETH_DEVICE_IP = """inet 172.18.204.10/25 brd 172.18.204.127 scope global \
eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::a60:6eff:fe6f:6da2/64 scope link
       valid_lft forever preferred_lft forever
"""

_ETH_DEVICE = _ETH_DEVICE_NO_IP + _ETH_DEVICE_IP

_DOCKER_DEVICE = """docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 \
qdisc noqueue state DOWN group default
    link/ether 56:86:7a:fe:97:79 brd ff:ff:ff:ff:ff:ff
    inet 172.17.42.1/16 scope global docker0

"""


class ExecuteTestCase(unittest2.TestCase):
    """This class is partly based on the same class in openstack/ironic."""

    def setUp(self):
        super(ExecuteTestCase, self).setUp()
        fake_driver = stevedore.extension.Extension('fake_driver', None, None,
                                                    mock.MagicMock)
        self.drv_manager = stevedore.driver.DriverManager.make_test_instance(
            fake_driver)

    def test_parse_unit(self):
        self.assertEqual(utils.parse_unit('1.00m', 'm', ceil=True), 1)
        self.assertEqual(utils.parse_unit('1.00m', 'm', ceil=False), 1)
        self.assertEqual(utils.parse_unit('1.49m', 'm', ceil=True), 2)
        self.assertEqual(utils.parse_unit('1.49m', 'm', ceil=False), 1)
        self.assertEqual(utils.parse_unit('1.51m', 'm', ceil=True), 2)
        self.assertEqual(utils.parse_unit('1.51m', 'm', ceil=False), 1)
        self.assertRaises(ValueError, utils.parse_unit, '1.00m', 'MiB')
        self.assertRaises(ValueError, utils.parse_unit, '', 'MiB')

    def test_B2MiB(self):
        self.assertEqual(utils.B2MiB(1048575, ceil=False), 0)
        self.assertEqual(utils.B2MiB(1048576, ceil=False), 1)
        self.assertEqual(utils.B2MiB(1048575, ceil=True), 1)
        self.assertEqual(utils.B2MiB(1048576, ceil=True), 1)
        self.assertEqual(utils.B2MiB(1048577, ceil=True), 2)

    def test_check_exit_code_boolean(self):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        self.assertRaises(errors.ProcessExecutionError,
                          utils.execute,
                          '/usr/bin/env', 'false', check_exit_code=True)

    @mock.patch('fuel_agent.utils.utils.time.sleep')
    @mock.patch('fuel_agent.utils.utils.subprocess.Popen')
    def test_execute_ok_on_third_attempts(self, mock_popen, mock_sleep):
        process = mock.Mock()
        mock_popen.side_effect = [OSError, ValueError, process]
        process.communicate.return_value = (None, None)
        process.returncode = 0
        utils.execute('/usr/bin/env', 'false', attempts=3)
        self.assertEqual(2 * [mock.call(CONF.execute_retry_delay)],
                         mock_sleep.call_args_list)

    @mock.patch('fuel_agent.utils.utils.time.sleep')
    @mock.patch('fuel_agent.utils.utils.subprocess.Popen')
    def test_execute_failed(self, mock_popen, mock_sleep):
        mock_popen.side_effect = OSError
        self.assertRaises(errors.ProcessExecutionError, utils.execute,
                          '/usr/bin/env', 'false', attempts=2)
        self.assertEqual(1 * [mock.call(CONF.execute_retry_delay)],
                         mock_sleep.call_args_list)

    @mock.patch('stevedore.driver.DriverManager')
    def test_get_driver(self, mock_drv_manager):
        mock_drv_manager.return_value = self.drv_manager
        self.assertEqual(mock.MagicMock.__name__,
                         utils.get_driver('fake_driver').__name__)

    @mock.patch('jinja2.Environment')
    @mock.patch('jinja2.FileSystemLoader')
    @mock.patch('six.moves.builtins.open')
    def test_render_and_save_fail(self, mock_open, mock_j_lo, mock_j_env):
        mock_open.side_effect = Exception('foo')
        self.assertRaises(errors.TemplateWriteError, utils.render_and_save,
                          'fake_dir', 'fake_tmpl_name', 'fake_data',
                          'fake_file_name')

    @mock.patch('jinja2.Environment')
    @mock.patch('jinja2.FileSystemLoader')
    @mock.patch('six.moves.builtins.open')
    def test_render_and_save_ok(self, mock_open, mock_j_lo, mock_j_env):
        mock_render = mock.Mock()
        mock_render.render.return_value = 'fake_data'
        mock_j_env.get_template.return_value = mock_render
        utils.render_and_save('fake_dir', 'fake_tmpl_name', 'fake_data',
                              'fake_file_name')
        mock_open.assert_called_once_with('fake_file_name', 'w')

    def test_calculate_md5_ok(self):
        # calculated by 'printf %10000s | md5sum'
        mock_open = mock.Mock()
        mock_open.__enter__ = mock.Mock(
            side_effect=(six.BytesIO(b' ' * 10000) for _ in range(6)))

        mock_open.__exit__ = mock.Mock(return_value=False)
        with mock.patch('six.moves.builtins.open',
                        mock.Mock(return_value=mock_open), create=True):
            self.assertEqual('f38898bb69bb02bccb9594dfe471c5c0',
                             utils.calculate_md5('fake', 10000))
            self.assertEqual('6934d9d33cd2d0c005994e7d96d2e0d9',
                             utils.calculate_md5('fake', 1000))
            self.assertEqual('1e68934346ee57858834a205017af8b7',
                             utils.calculate_md5('fake', 100))
            self.assertEqual('41b394758330c83757856aa482c79977',
                             utils.calculate_md5('fake', 10))
            self.assertEqual('7215ee9c7d9dc229d2921a40e899ec5f',
                             utils.calculate_md5('fake', 1))
            self.assertEqual('d41d8cd98f00b204e9800998ecf8427e',
                             utils.calculate_md5('fake', 0))

    def test_should_bypass_proxy_true(self):
        hostname = 'fake.hostname.11.42'
        url = "http://{0}/place?query".format(hostname)
        self.assertTrue(utils.should_bypass_proxy(
            url, [hostname]))

    def test_should_bypass_proxy_false(self):
        self.assertFalse(utils.should_bypass_proxy(
            'http://fake.hostname.11.42', ['0.0.0.0']))

    @mock.patch.object(requests, 'get')
    def test_init_http_request_proxy(self, mock_req):
        proxies = {'http': 'proxy1'}
        noproxy_addrs = ['fake.hostname.11.42']
        utils.init_http_request('http://fake_url',
                                proxies=proxies,
                                noproxy_addrs=noproxy_addrs)
        mock_req.assert_called_once_with(
            'http://fake_url', stream=True, timeout=CONF.http_request_timeout,
            headers={'Range': 'bytes=0-'}, proxies=proxies)

    @mock.patch.object(requests, 'get')
    def test_init_http_requests_bypass_proxy(self, mock_req):
        proxies = {'http': 'proxy1'}
        hostname = 'fake.hostname.11.42'
        url = "http://{0}/web".format(hostname)
        noproxy_addrs = [hostname]
        utils.init_http_request(url,
                                proxies=proxies,
                                noproxy_addrs=noproxy_addrs)
        mock_req.assert_called_once_with(
            url, stream=True, timeout=CONF.http_request_timeout,
            headers={'Range': 'bytes=0-'}, proxies=None)

    @mock.patch.object(requests, 'get')
    def test_init_http_request_ok(self, mock_req):
        utils.init_http_request('http://fake_url')
        mock_req.assert_called_once_with(
            'http://fake_url', stream=True, timeout=CONF.http_request_timeout,
            headers={'Range': 'bytes=0-'}, proxies=None)

    @mock.patch('time.sleep')
    @mock.patch.object(requests, 'get')
    def test_init_http_request_non_critical_errors(self, mock_req, mock_s):
        mock_ok = mock.Mock()
        mock_req.side_effect = [urllib3.exceptions.DecodeError(),
                                urllib3.exceptions.ProxyError(),
                                requests.exceptions.ConnectionError(),
                                requests.exceptions.Timeout(),
                                requests.exceptions.TooManyRedirects(),
                                socket.timeout(),
                                mock_ok]
        req_obj = utils.init_http_request('http://fake_url')
        self.assertEqual(mock_ok, req_obj)

    @mock.patch.object(requests, 'get')
    def test_init_http_request_wrong_http_status(self, mock_req):
        mock_fail = mock.Mock()
        mock_fail.raise_for_status.side_effect = KeyError()
        mock_req.return_value = mock_fail
        self.assertRaises(KeyError, utils.init_http_request, 'http://fake_url')

    @mock.patch('time.sleep')
    @mock.patch.object(requests, 'get')
    def test_init_http_request_max_retries_exceeded(self, mock_req, mock_s):
        mock_req.side_effect = requests.exceptions.ConnectionError()
        self.assertRaises(errors.HttpUrlConnectionError,
                          utils.init_http_request, 'http://fake_url')

    @mock.patch('time.sleep')
    @mock.patch.object(requests, 'get')
    def test_init_http_request_max_retries_exceeded_HTTPerror(
            self, mock_req, mock_s):
        mock_req.side_effect = requests.exceptions.HTTPError
        self.assertRaises(errors.HttpUrlConnectionError,
                          utils.init_http_request, 'http://fake_url')

    @mock.patch('fuel_agent.utils.utils.os.makedirs')
    @mock.patch('fuel_agent.utils.utils.os.path.isdir', return_value=False)
    def test_makedirs_if_not_exists(self, mock_isdir, mock_makedirs):
        utils.makedirs_if_not_exists('/fake/path')
        mock_isdir.assert_called_once_with('/fake/path')
        mock_makedirs.assert_called_once_with('/fake/path', mode=0o755)

    @mock.patch('fuel_agent.utils.utils.os.makedirs')
    @mock.patch('fuel_agent.utils.utils.os.path.isdir', return_value=False)
    def test_makedirs_if_not_exists_mode_given(
            self, mock_isdir, mock_makedirs):
        utils.makedirs_if_not_exists('/fake/path', mode=0o000)
        mock_isdir.assert_called_once_with('/fake/path')
        mock_makedirs.assert_called_once_with('/fake/path', mode=0o000)

    @mock.patch('fuel_agent.utils.utils.os.makedirs')
    @mock.patch('fuel_agent.utils.utils.os.path.isdir', return_value=True)
    def test_makedirs_if_not_exists_already_exists(
            self, mock_isdir, mock_makedirs):
        utils.makedirs_if_not_exists('/fake/path')
        mock_isdir.assert_called_once_with('/fake/path')
        self.assertEqual(mock_makedirs.mock_calls, [])

    @mock.patch('fuel_agent.utils.utils.os.listdir')
    def test_guess_filename(self, mock_oslistdir):
        mock_oslistdir.return_value = ['file1', 'file2', 'file3']
        filename = utils.guess_filename('/some/path', '^file2.*')
        self.assertEqual(filename, 'file2')
        mock_oslistdir.assert_called_once_with('/some/path')

    @mock.patch('fuel_agent.utils.utils.os.listdir')
    def test_guess_filename_not_found(self, mock_oslistdir):
        mock_oslistdir.return_value = ['file1', 'file2', 'file3']
        filename = utils.guess_filename('/some/path', '^file4.*')
        self.assertIsNone(filename)
        mock_oslistdir.assert_called_once_with('/some/path')

    @mock.patch('fuel_agent.utils.utils.os.listdir')
    def test_guess_filename_not_exact_match(self, mock_oslistdir):
        mock_oslistdir.return_value = ['file1', 'file2', 'file3']
        filename = utils.guess_filename('/some/path', '^file.*')
        # by default files are sorted in backward direction
        self.assertEqual(filename, 'file3')
        mock_oslistdir.assert_called_once_with('/some/path')

    @mock.patch('fuel_agent.utils.utils.os.listdir')
    def test_guess_filename_not_exact_match_forward_sort(self, mock_oslistdir):
        mock_oslistdir.return_value = ['file1', 'file2', 'file3']
        filename = utils.guess_filename('/some/path', '^file.*', reverse=False)
        # by default files are sorted in backward direction
        self.assertEqual(filename, 'file1')
        mock_oslistdir.assert_called_once_with('/some/path')

    @mock.patch.object(utils, 'execute')
    def test_udevadm_settle(self, mock_exec):
        utils.udevadm_settle()
        mock_exec.assert_called_once_with('udevadm', 'settle',
                                          check_exit_code=[0])

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'wait_for_udev_settle')
    def test_udevadm_trigger_blocks(self, mock_wait, mock_exec):
        utils.udevadm_trigger_blocks()
        mock_exec.assert_called_once_with(
            'udevadm', 'trigger', '--subsystem-match=block')
        self.assertTrue(mock_wait.called)

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'wait_for_udev_settle')
    def test_multipath_refresh(self, mock_wait, mock_exec):
        utils.refresh_multipath()
        call_list = mock_exec.call_args_list
        self.assertEqual(call_list, [
            mock.call('dmsetup', 'remove_all'),
            mock.call('multipath', '-F'),
            mock.call('multipath', '-r')])
        self.assertTrue(mock_wait.called)


@mock.patch.object(utils, 'open', create=True, new_callable=mock.mock_open)
@mock.patch.object(utils, 'os', autospec=True)
@mock.patch.object(utils, 'execute')
@mock.patch.object(utils, 'udevadm_settle')
class TestUdevRulesBlacklisting(unittest2.TestCase):
    @staticmethod
    def _fake_join(path1, path2):
        return '{0}/{1}'.format(path1, path2)

    def test_blacklist_udev_rules_rule_exists(self, mock_udev, mock_execute,
                                              mock_os, mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.path.basename.return_value = 'fake_basename'
        mock_os.listdir.return_value = ['fake.rules', 'fake_err.rules']
        mock_os.path.isdir.return_value = False
        mock_os.path.exists.return_value = True
        mock_os.rename.side_effect = [None, OSError]
        utils.blacklist_udev_rules('/etc/udev/rules.d', '/lib/udev/rules.d',
                                   '.renamedrule', 'empty_rule')
        self.assertEqual([mock.call('/etc/udev/rules.d/fake.rules'),
                          mock.call('/etc/udev/rules.d/fake_err.rules')],
                         mock_os.path.exists.call_args_list)
        self.assertEqual([mock.call('/etc/udev/rules.d/fake.rules',
                                    '/etc/udev/rules.d/fake.renamedrule'),
                          mock.call('/etc/udev/rules.d/fake_err.rules',
                                    '/etc/udev/rules.d/fake_err.renamedrule')],
                         mock_os.rename.call_args_list)
        self.assertEqual([mock.call('/etc/udev/rules.d', 'fake_basename'),
                          mock.call('/etc/udev/rules.d', 'fake.rules'),
                          mock.call('/etc/udev/rules.d', 'fake_err.rules')],
                         mock_os.path.join.call_args_list)
        mock_os.symlink.assert_called_once_with(
            '/etc/udev/rules.d/fake_basename',
            '/etc/udev/rules.d/fake.rules')
        self.assertEqual(2 * [mock.call()], mock_udev.call_args_list)

    def test_blacklist_udev_rules_rule_doesnot_exist(self, mock_udev,
                                                     mock_execute, mock_os,
                                                     mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.path.basename.return_value = 'fake_basename'
        mock_os.listdir.return_value = ['fake.rules']
        mock_os.path.isdir.return_value = False
        mock_os.path.exists.return_value = False
        utils.blacklist_udev_rules('/etc/udev/rules.d', '/lib/udev/rules.d',
                                   '.renamedrule', 'empty_rule')
        self.assertFalse(mock_os.rename.called)
        mock_os.path.isdir.assert_called_once_with(
            '/etc/udev/rules.d/fake.rules')
        mock_os.path.exists.assert_called_once_with(
            '/etc/udev/rules.d/fake.rules')
        self.assertEqual([mock.call('/etc/udev/rules.d', 'fake_basename'),
                          mock.call('/etc/udev/rules.d', 'fake.rules')],
                         mock_os.path.join.call_args_list)
        mock_os.symlink.assert_called_once_with(
            '/etc/udev/rules.d/fake_basename',
            '/etc/udev/rules.d/fake.rules')
        mock_udev.assert_called_once_with()

    def test_blacklist_udev_rules_not_a_rule(self, mock_udev, mock_execute,
                                             mock_os, mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.path.basename.return_value = 'fake_basename'
        mock_os.listdir.return_value = ['not_a_rule', 'dir']
        mock_os.path.isdir.side_effect = [False, True]
        utils.blacklist_udev_rules('/etc/udev/rules.d', '/lib/udev/rules.d',
                                   '.renamedrule', 'empty_rule')
        self.assertFalse(mock_udev.called)
        self.assertFalse(mock_os.symlink.called)
        self.assertFalse(mock_os.rename.called)
        self.assertFalse(mock_os.path.exists.called)
        mock_os.listdir.assert_called_once_with('/lib/udev/rules.d')
        self.assertEqual([mock.call('/etc/udev/rules.d/not_a_rule'),
                          mock.call('/etc/udev/rules.d/dir')],
                         mock_os.path.isdir.call_args_list)
        self.assertEqual([mock.call('/etc/udev/rules.d', 'fake_basename'),
                          mock.call('/etc/udev/rules.d', 'not_a_rule'),
                          mock.call('/etc/udev/rules.d', 'dir')],
                         mock_os.path.join.call_args_list)

    def test_blacklist_udev_rules_create_empty_rule(self, mock_udev,
                                                    mock_execute, mock_os,
                                                    mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.path.basename.return_value = 'fake_basename'
        utils.blacklist_udev_rules('/etc/udev/rules.d', '/lib/udev/rules.d',
                                   '.renamedrule', 'empty_rule')
        mock_open.assert_called_once_with('/etc/udev/rules.d/fake_basename',
                                          'w')
        file_handler = mock_open.return_value.__enter__.return_value
        file_handler.write.assert_called_once_with('#\n')
        mock_os.path.basename.assert_called_once_with('empty_rule')

    def test_blacklist_udev_rules_execute(self, mock_udev, mock_execute,
                                          mock_os, mock_open):
        utils.blacklist_udev_rules('/etc/udev/rules.d', '/lib/udev/rules.d',
                                   '.renamedrule', 'empty_rule')
        mock_execute.assert_called_once_with(
            'udevadm', 'control', '--reload-rules', check_exit_code=[0])

    def test_unblacklist_udev_rules_remove(self, mock_udev, mock_execute,
                                           mock_os, mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.listdir.return_value = ['fake.rules', 'fake_err.rules']
        mock_os.remove.side_effect = [None, OSError]
        mock_os.path.isdir.side_effect = 2 * [False]
        mock_os.path.islink.return_value = True
        utils.unblacklist_udev_rules('/etc/udev/rules.d', '.renamedrule')
        self.assertFalse(mock_os.path.exists.called)
        self.assertFalse(mock_os.rename.called)
        mock_os.listdir.assert_called_once_with('/etc/udev/rules.d')
        expected_rules_calls = [mock.call('/etc/udev/rules.d/fake.rules'),
                                mock.call('/etc/udev/rules.d/fake_err.rules')]
        self.assertEqual(expected_rules_calls,
                         mock_os.path.islink.call_args_list)
        self.assertEqual(expected_rules_calls,
                         mock_os.remove.call_args_list)
        self.assertEqual(2 * [mock.call()], mock_udev.call_args_list)

    def test_unblacklist_udev_rules_executes(self, mock_udev, mock_execute,
                                             mock_os, mock_open):
        utils.unblacklist_udev_rules('/etc/udev/rules.d', '.renamedrule')
        self.assertEqual([mock.call('udevadm', 'control', '--reload-rules',
                                    check_exit_code=[0]),
                          mock.call('udevadm', 'trigger',
                                    '--subsystem-match=block',
                                    check_exit_code=[0])],
                         mock_execute.call_args_list)

    def test_unblacklist_udev_rules_rename(self, mock_udev, mock_execute,
                                           mock_os, mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.listdir.return_value = ['fake.renamedrule',
                                        'fake_err.renamedrule']
        mock_os.rename.side_effect = [None, OSError]
        mock_os.path.isdir.side_effect = 2 * [False]
        utils.unblacklist_udev_rules('/etc/udev/rules.d', '.renamedrule')
        self.assertFalse(mock_os.path.islink.called)
        self.assertFalse(mock_os.remove.called)
        mock_os.listdir.assert_called_once_with('/etc/udev/rules.d')
        self.assertEqual([mock.call('/etc/udev/rules.d/fake.renamedrule'),
                          mock.call('/etc/udev/rules.d/fake_err.renamedrule')],
                         mock_os.path.exists.call_args_list)
        self.assertEqual([mock.call('/etc/udev/rules.d/fake.renamedrule',
                                    '/etc/udev/rules.d/fake.rules'),
                          mock.call('/etc/udev/rules.d/fake_err.renamedrule',
                                    '/etc/udev/rules.d/fake_err.rules')],
                         mock_os.rename.call_args_list)
        self.assertEqual(2 * [mock.call()], mock_udev.call_args_list)

    def test_unblacklist_udev_rules_not_a_rule(self, mock_udev, mock_execute,
                                               mock_os, mock_open):
        mock_os.path.join.side_effect = self._fake_join
        mock_os.listdir.return_value = ['not_a_rule', 'dir']
        mock_os.path.isdir.side_effect = [False, True]
        utils.unblacklist_udev_rules('/etc/udev/rules.d', '.renamedrule')
        mock_os.listdir.assert_called_once_with('/etc/udev/rules.d')
        self.assertEqual([mock.call('/etc/udev/rules.d', 'not_a_rule'),
                          mock.call('/etc/udev/rules.d', 'dir')],
                         mock_os.path.join.call_args_list)
        self.assertEqual([mock.call('/etc/udev/rules.d/not_a_rule'),
                          mock.call('/etc/udev/rules.d/dir')],
                         mock_os.path.isdir.call_args_list)
        self.assertFalse(mock_os.path.exists.called)
        self.assertFalse(mock_os.remove.called)
        self.assertFalse(mock_os.rename.called)
        mock_udev.assert_called_once_with()


@mock.patch.object(utils, 'execute')
class GetIPTestCase(unittest2.TestCase):

    def setUp(self):
        super(GetIPTestCase, self).setUp()
        self.mac = '08:60:6e:6f:7d:a5'
        self.cmd = ('ip', 'addr', 'show', 'scope', 'global')

    def _build_out(self, lines):
        out = ''
        for num, line in enumerate(lines, start=1):
            out += str(num) + ': ' + line
        return out

    def test_get_interface_ip(self, mock_execute):
        lines = _LO_DEVICE, _ETH_DEVICE, _DOCKER_DEVICE
        out = self._build_out(lines)
        mock_execute.return_value = out, ''
        ip = utils.get_interface_ip(self.mac)
        self.assertEqual('172.18.204.10', ip)
        mock_execute.assert_called_once_with(*self.cmd)

    def test_get_interface_no_mac(self, mock_execute):
        lines = _LO_DEVICE, _DOCKER_DEVICE
        out = self._build_out(lines)
        mock_execute.return_value = out, ''
        ip = utils.get_interface_ip(self.mac)
        self.assertIsNone(ip)
        mock_execute.assert_called_once_with(*self.cmd)

    def test_get_interface_no_ip(self, mock_execute):
        lines = _LO_DEVICE, _ETH_DEVICE_NO_IP, _DOCKER_DEVICE
        out = self._build_out(lines)
        mock_execute.return_value = out, ''
        ip = utils.get_interface_ip(self.mac)
        self.assertIsNone(ip)
        mock_execute.assert_called_once_with(*self.cmd)

    def test_get_interface_no_ip_last(self, mock_execute):
        lines = _LO_DEVICE, _ETH_DEVICE_NO_IP
        out = self._build_out(lines)
        mock_execute.return_value = out, ''
        ip = utils.get_interface_ip(self.mac)
        self.assertIsNone(ip)
        mock_execute.assert_called_once_with(*self.cmd)


class ParseKernelCmdline(unittest2.TestCase):

    def test_parse_kernel_cmdline(self):
        data = 'foo=bar baz abc=def=123'
        with mock.patch('six.moves.builtins.open',
                        mock.mock_open(read_data=data)) as mock_open:
            params = utils.parse_kernel_cmdline()
            self.assertEqual('bar', params['foo'])
            mock_open.assert_called_once_with('/proc/cmdline', 'rt')

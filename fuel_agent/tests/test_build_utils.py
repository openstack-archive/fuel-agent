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

import os
import shutil
import signal
import time

import mock
import unittest2

from fuel_agent import errors
from fuel_agent.utils import build as bu
from fuel_agent.utils import hardware as hu
from fuel_agent.utils import utils


class BuildUtilsTestCase(unittest2.TestCase):

    _fake_ubuntu_release = '''
      Origin: TestOrigin
      Label: TestLabel
      Archive: test-archive
      Codename: testcodename
    '''

    def setUp(self):
        super(BuildUtilsTestCase, self).setUp()

    @mock.patch('fuel_agent.utils.build.os', environ={})
    @mock.patch.object(utils, 'execute', return_value=(None, None))
    def test_run_debootstrap(self, mock_exec, mock_environ):
        bu.run_debootstrap('uri', 'suite', 'chroot', 'arch', attempts=2)
        mock_exec.assert_called_once_with(
            'debootstrap', '--include={0}'
            .format(','.join(bu.ADDITIONAL_DEBOOTSTRAP_PACKAGES)),
            '--verbose', '--no-check-gpg', '--arch=arch',
            'suite', 'chroot', 'uri', attempts=2, env_variables={})

    @mock.patch('fuel_agent.utils.build.os', environ={})
    @mock.patch.object(utils, 'execute', return_value=(None, None))
    def test_run_debootstrap_eatmydata(self, mock_exec, mock_environ):
        bu.run_debootstrap('uri', 'suite', 'chroot', 'arch', eatmydata=True,
                           attempts=2)
        mock_exec.assert_called_once_with(
            'debootstrap', '--include={0}'
            .format(','.join(bu.ADDITIONAL_DEBOOTSTRAP_PACKAGES)),
            '--verbose', '--no-check-gpg', '--arch=arch',
            '--include=eatmydata', 'suite',
            'chroot', 'uri', attempts=2, env_variables={})

    @mock.patch.object(utils, 'execute', return_value=(None, None))
    def test_run_apt_get(self, mock_exec):
        bu.run_apt_get('chroot', ['package1', 'package2'], attempts=2)
        mock_exec_expected_calls = [
            mock.call('chroot', 'chroot', 'apt-get', '-y', 'update',
                      attempts=2),
            mock.call('chroot', 'chroot', 'apt-get', '-y', 'dist-upgrade',
                      attempts=2),
            mock.call('chroot', 'chroot', 'apt-get', '-y', 'install',
                      'package1 package2', attempts=2)]
        self.assertEqual(mock_exec_expected_calls, mock_exec.call_args_list)

    @mock.patch.object(utils, 'execute', return_value=(None, None))
    def test_run_apt_get_eatmydata(self, mock_exec):
        bu.run_apt_get('chroot', ['package1', 'package2'], eatmydata=True,
                       attempts=2)
        mock_exec_expected_calls = [
            mock.call('chroot', 'chroot', 'apt-get', '-y', 'update',
                      attempts=2),
            mock.call('chroot', 'chroot', 'apt-get', '-y', 'dist-upgrade',
                      attempts=2),
            mock.call('chroot', 'chroot', 'eatmydata', 'apt-get', '-y',
                      'install', 'package1 package2', attempts=2)]
        self.assertEqual(mock_exec_expected_calls, mock_exec.call_args_list)

    @mock.patch.object(os, 'fchmod')
    @mock.patch.object(os, 'makedirs')
    @mock.patch.object(os, 'path')
    def test_suppress_services_start(self, mock_path, mock_mkdir, mock_fchmod):
        mock_path.join.return_value = 'fake_path'
        mock_path.exists.return_value = False
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            file_handle_mock.fileno.return_value = 'fake_fileno'
            bu.suppress_services_start('chroot')
            mock_open.assert_called_once_with('fake_path', 'w')
            expected = '#!/bin/sh\n# prevent any service from being started\n'\
                       'exit 101\n'
            file_handle_mock.write.assert_called_once_with(expected)
            mock_fchmod.assert_called_once_with('fake_fileno', 0o755)
        mock_mkdir.assert_called_once_with('fake_path')

    @mock.patch.object(os, 'fchmod')
    @mock.patch.object(os, 'path')
    def test_suppress_services_start_nomkdir(self, mock_path, mock_fchmod):
        mock_path.join.return_value = 'fake_path'
        mock_path.exists.return_value = True
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            file_handle_mock.fileno.return_value = 'fake_fileno'
            bu.suppress_services_start('chroot')
            mock_open.assert_called_once_with('fake_path', 'w')
            expected = '#!/bin/sh\n# prevent any service from being started\n'\
                       'exit 101\n'
            file_handle_mock.write.assert_called_once_with(expected)
            mock_fchmod.assert_called_once_with('fake_fileno', 0o755)

    @mock.patch.object(shutil, 'rmtree')
    @mock.patch.object(os, 'makedirs')
    @mock.patch.object(os, 'path')
    def test_clean_dirs(self, mock_path, mock_mkdir, mock_rmtree):
        mock_path.isdir.return_value = True
        dirs = ['dir1', 'dir2', 'dir3']
        mock_path.join.side_effect = dirs
        bu.clean_dirs('chroot', dirs)
        for m in (mock_rmtree, mock_mkdir):
            self.assertEqual([mock.call(d) for d in dirs], m.call_args_list)

    @mock.patch.object(os, 'path')
    def test_clean_dirs_not_isdir(self, mock_path):
        mock_path.isdir.return_value = False
        dirs = ['dir1', 'dir2', 'dir3']
        mock_path.join.side_effect = dirs
        bu.clean_dirs('chroot', dirs)
        self.assertEqual([mock.call('chroot', d) for d in dirs],
                         mock_path.join.call_args_list)

    @mock.patch.object(os, 'remove')
    @mock.patch.object(os, 'path')
    def test_remove_files(self, mock_path, mock_remove):
        mock_path.exists.return_value = True
        files = ['file1', 'file2', 'dir3']
        mock_path.join.side_effect = files
        bu.remove_files('chroot', files)
        self.assertEqual([mock.call(f) for f in files],
                         mock_remove.call_args_list)

    @mock.patch.object(os, 'path')
    def test_remove_files_not_exists(self, mock_path):
        mock_path.exists.return_value = False
        files = ['file1', 'file2', 'dir3']
        mock_path.join.side_effect = files
        bu.remove_files('chroot', files)
        self.assertEqual([mock.call('chroot', f) for f in files],
                         mock_path.join.call_args_list)

    @mock.patch.object(bu, 'remove_files')
    @mock.patch.object(bu, 'clean_dirs')
    def test_clean_apt_settings(self, mock_dirs, mock_files):
        bu.clean_apt_settings('chroot', 'unsigned', 'force_ipv4',
                              'pipeline_depth', 'install_rule')
        mock_dirs.assert_called_once_with(
            'chroot', ['etc/apt/preferences.d', 'etc/apt/sources.list.d'])
        files = set(['etc/apt/sources.list', 'etc/apt/preferences',
                     'etc/apt/apt.conf.d/%s' % 'force_ipv4',
                     'etc/apt/apt.conf.d/%s' % 'unsigned',
                     'etc/apt/apt.conf.d/%s' % 'pipeline_depth',
                     'etc/apt/apt.conf.d/01fuel_agent-use-proxy-ftp',
                     'etc/apt/apt.conf.d/01fuel_agent-use-proxy-http',
                     'etc/apt/apt.conf.d/01fuel_agent-use-proxy-https',
                     'etc/apt/apt.conf.d/%s' % 'install_rule',
                     ])
        self.assertEqual('chroot', mock_files.call_args[0][0])
        self.assertEqual(files, set(mock_files.call_args[0][1]))

    @mock.patch('fuel_agent.utils.build.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.utils.build.yaml.safe_dump')
    @mock.patch('fuel_agent.utils.build.yaml.safe_load',
                return_value={'cloud_init_modules': ['write-files', 'ssh'],
                              'cloud_config_modules': ['runcmd']
                              }
                )
    def test_fix_cloud_init_config(self, mock_yaml_load, mock_yaml_dump,
                                   mock_open):
        bu.fix_cloud_init_config('fake_path')
        mock_yaml_dump.assert_called_once_with({
            'cloud_init_modules': ['ssh'],
            'cloud_config_modules': ['runcmd', 'write-files']
        }, mock.ANY, encoding='utf-8', default_flow_style=False)

    @mock.patch('fuel_agent.utils.build.os.unlink')
    @mock.patch('fuel_agent.utils.build.os.mkdir')
    @mock.patch('fuel_agent.utils.build.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.utils.build.os.path')
    @mock.patch.object(bu, 'clean_apt_settings')
    @mock.patch.object(bu, 'remove_files')
    @mock.patch.object(utils, 'execute')
    @mock.patch('fuel_agent.utils.build.yaml.safe_dump')
    @mock.patch('fuel_agent.utils.build.yaml.safe_load')
    def test_do_post_inst(self, mock_yaml_load, mock_yaml_dump, mock_exec,
                          mock_files, mock_clean, mock_path,
                          mock_open, mock_mkdir, mock_unlink):
        mock_path.join.return_value = 'fake_path'
        mock_path.exists.return_value = True

        # crypt.crypt('qwerty')
        password = ('$6$KyOsgFgf9cLbGNST$Ej0Usihfy7W/WT2H0z0mC1DapC/IUpA0jF'
                    '.Fs83mFIdkGYHL9IOYykRCjfssH.YL4lHbmrvOd/6TIfiyh1hDY1')

        bu.do_post_inst('chroot',
                        hashed_root_password=password,
                        allow_unsigned_file='fake_unsigned',
                        force_ipv4_file='fake_force_ipv4',
                        pipeline_depth_file='fake_pipeline_depth',
                        install_rule_file='fake_install_rule')

        file_handle_mock = mock_open.return_value.__enter__.return_value
        file_handle_mock.write.assert_called_once_with('manual\n')

        mock_exec_expected_calls = [
            mock.call('sed',
                      '-i',
                      's%root:[\*,\!]%root:{}%'.format(password),
                      'fake_path'),
            mock.call('chroot', 'chroot', 'update-rc.d', 'puppet', 'disable'),
            mock.call('chroot', 'chroot', 'dpkg-divert', '--local', '--add',
                      'fake_path'),
            mock.call('chroot', 'chroot', 'apt-get', 'clean')]

        self.assertEqual(mock_exec_expected_calls, mock_exec.call_args_list)
        self.assertEqual([mock.call('chroot', ['usr/sbin/policy-rc.d']),
                          mock.call('chroot', [bu.GRUB2_DMRAID_SETTINGS])],
                         mock_files.call_args_list)
        mock_clean.assert_called_once_with(
            'chroot',
            allow_unsigned_file='fake_unsigned',
            force_ipv4_file='fake_force_ipv4',
            pipeline_depth_file='fake_pipeline_depth',
            install_rule_file='fake_install_rule')
        mock_path_join_expected_calls = [
            mock.call('chroot', 'etc/shadow'),
            mock.call('chroot', 'etc/init.d/puppet'),
            mock.call('chroot', 'etc/init/mcollective.override'),
            mock.call('chroot',
                      'etc/systemd/system'
                      '/multi-user.target.wants/mcollective.service'),
            mock.call('chroot', 'etc/cloud/cloud.cfg.d/'),
            mock.call('chroot',
                      'etc/cloud/cloud.cfg.d/99-disable-network-config.cfg'),
            mock.call('chroot', 'etc/cloud/cloud.cfg'),
            mock.call('/', bu.GRUB2_DMRAID_SETTINGS)]
        self.assertEqual(mock_path_join_expected_calls,
                         mock_path.join.call_args_list)
        mock_unlink.assert_called_once_with('fake_path')
        mock_yaml_dump.assert_called_with(mock.ANY,
                                          mock.ANY,
                                          encoding='utf-8',
                                          default_flow_style=False)

    @mock.patch('fuel_agent.utils.build.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.utils.build.time.sleep')
    @mock.patch.object(os, 'kill')
    @mock.patch.object(os, 'readlink', return_value='chroot')
    @mock.patch.object(utils, 'execute')
    def test_stop_chrooted_processes(self, mock_exec, mock_link,
                                     mock_kill, mock_sleep, mock_open):
        mock_exec.side_effect = [
            ('kernel   951  1641  1700  1920  3210  4104', ''),
            ('kernel   951  1641  1700', ''),
            ('', '')]
        mock_exec_expected_calls = \
            [mock.call('fuser', '-v', 'chroot', check_exit_code=False)] * 3

        bu.stop_chrooted_processes('chroot', signal=signal.SIGTERM)
        self.assertEqual(mock_exec_expected_calls, mock_exec.call_args_list)

        expected_mock_link_calls = [
            mock.call('/proc/951/root'),
            mock.call('/proc/1641/root'),
            mock.call('/proc/1700/root'),
            mock.call('/proc/1920/root'),
            mock.call('/proc/3210/root'),
            mock.call('/proc/4104/root'),
            mock.call('/proc/951/root'),
            mock.call('/proc/1641/root'),
            mock.call('/proc/1700/root')]
        expected_mock_kill_calls = [
            mock.call(951, signal.SIGTERM),
            mock.call(1641, signal.SIGTERM),
            mock.call(1700, signal.SIGTERM),
            mock.call(1920, signal.SIGTERM),
            mock.call(3210, signal.SIGTERM),
            mock.call(4104, signal.SIGTERM),
            mock.call(951, signal.SIGTERM),
            mock.call(1641, signal.SIGTERM),
            mock.call(1700, signal.SIGTERM)]
        self.assertEqual(expected_mock_link_calls, mock_link.call_args_list)
        self.assertEqual(expected_mock_kill_calls, mock_kill.call_args_list)

    @mock.patch.object(os, 'makedev', return_value='fake_dev')
    @mock.patch.object(os, 'mknod')
    @mock.patch.object(os, 'path')
    @mock.patch.object(utils, 'execute', return_value=('/dev/loop123\n', ''))
    def test_get_free_loop_device_ok(self, mock_exec, mock_path, mock_mknod,
                                     mock_mkdev):
        mock_path.exists.return_value = False
        self.assertEqual('/dev/loop123', bu.get_free_loop_device(1))
        mock_exec.assert_called_once_with('losetup', '--find')
        mock_path.exists.assert_called_once_with('/dev/loop0')
        mock_mknod.assert_called_once_with('/dev/loop0', 25008, 'fake_dev')
        mock_mkdev.assert_called_once_with(1, 0)

    def test_set_apt_get_env(self):
        with mock.patch.dict('os.environ', {}):
            bu.set_apt_get_env()
            self.assertEqual('noninteractive', os.environ['DEBIAN_FRONTEND'])
            self.assertEqual('true', os.environ['DEBCONF_NONINTERACTIVE_SEEN'])
            for var in ('LC_ALL', 'LANG', 'LANGUAGE'):
                self.assertEqual('C', os.environ[var])

    def test_strip_filename(self):
        self.assertEqual('safe_Tex.-98',
                         bu.strip_filename('!@$^^^safe _Tex.?-98;'))

    @mock.patch.object(os, 'makedev', return_value='fake_dev')
    @mock.patch.object(os, 'mknod')
    @mock.patch.object(os, 'path')
    @mock.patch.object(utils, 'execute', return_value=('', 'Error!!!'))
    def test_get_free_loop_device_not_found(self, mock_exec, mock_path,
                                            mock_mknod, mock_mkdev):
        mock_path.exists.return_value = False
        self.assertRaises(errors.NoFreeLoopDevices, bu.get_free_loop_device)

    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch.object(utils, 'execute')
    def test_create_sparse_tmp_file(self, mock_exec, mock_temp):
        tmp_file = mock.Mock()
        tmp_file.name = 'fake_name'
        mock_temp.return_value = tmp_file
        bu.create_sparse_tmp_file('dir', 'suffix', 1)
        mock_temp.assert_called_once_with(dir='dir', suffix='suffix',
                                          delete=False)
        mock_exec.assert_called_once_with('truncate', '-s', '1M',
                                          tmp_file.name)

    @mock.patch.object(utils, 'execute')
    def test_attach_file_to_loop(self, mock_exec):
        bu.attach_file_to_loop('file', 'loop')
        mock_exec.assert_called_once_with('losetup', 'loop', 'file')

    @mock.patch.object(utils, 'execute')
    def test_deattach_loop(self, mock_exec):
        mock_exec.return_value = ('/dev/loop0: [fd03]:130820 (/dev/loop0)', '')
        bu.deattach_loop('/dev/loop0', check_exit_code='Fake')
        mock_exec_expected_calls = [
            mock.call('losetup', '-a'),
            mock.call('losetup', '-d', '/dev/loop0', check_exit_code='Fake')
        ]
        self.assertEqual(mock_exec.call_args_list, mock_exec_expected_calls)

    @mock.patch.object(hu, 'parse_simple_kv')
    @mock.patch.object(utils, 'execute')
    def test_shrink_sparse_file(self, mock_exec, mock_parse):
        mock_parse.return_value = {'block count': 1, 'block size': 2}
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            bu.shrink_sparse_file('file')
            mock_open.assert_called_once_with('file', 'rwb+')
            file_handle_mock.truncate.assert_called_once_with(1 * 2)
        expected_mock_exec_calls = [mock.call('e2fsck', '-y', '-f', 'file'),
                                    mock.call('resize2fs', '-M', 'file')]
        mock_parse.assert_called_once_with('dumpe2fs', 'file')
        self.assertEqual(expected_mock_exec_calls, mock_exec.call_args_list)

    @mock.patch.object(os, 'path')
    def test_add_apt_source(self, mock_path):
        mock_path.return_value = 'fake_path'
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            bu.add_apt_source('name1', 'uri1', 'suite1', 'section1', 'chroot')
            expected_calls = [mock.call('deb uri1 suite1 section1\n')]
            self.assertEqual(expected_calls,
                             file_handle_mock.write.call_args_list)
        expected_mock_path_calls = [
            mock.call('chroot', 'etc/apt/sources.list.d',
                      'fuel-image-name1.list')]
        self.assertEqual(expected_mock_path_calls,
                         mock_path.join.call_args_list)

    @mock.patch.object(os, 'path')
    def test_add_apt_source_no_section(self, mock_path):
        mock_path.return_value = 'fake_path'
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            bu.add_apt_source('name2', 'uri2', 'suite2', None, 'chroot')
            expected_calls = [mock.call('deb uri2 suite2\n')]
            self.assertEqual(expected_calls,
                             file_handle_mock.write.call_args_list)
        expected_mock_path_calls = [
            mock.call('chroot', 'etc/apt/sources.list.d',
                      'fuel-image-name2.list')]
        self.assertEqual(expected_mock_path_calls,
                         mock_path.join.call_args_list)

    @mock.patch.object(os, 'path')
    @mock.patch('fuel_agent.utils.build.utils.init_http_request',
                return_value=mock.Mock(text=_fake_ubuntu_release))
    def test_add_apt_preference(self, mock_get, mock_path):
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value

            fake_section = 'section1'
            bu.add_apt_preference(
                'name1',
                123,
                'test-archive',
                fake_section,
                'chroot',
                'http://test-uri'
            )

            calls_args = [
                c[0][0] for c in file_handle_mock.write.call_args_list
            ]

            self.assertEqual(len(calls_args), 4)
            self.assertEqual(calls_args[0], 'Package: *\n')
            self.assertEqual(calls_args[1], 'Pin: release ')
            self.assertIn("l=TestLabel", calls_args[2])
            self.assertIn("n=testcodename", calls_args[2])
            self.assertIn("a=test-archive", calls_args[2])
            self.assertIn("o=TestOrigin", calls_args[2])
            self.assertEqual(calls_args[3], 'Pin-Priority: 123\n')

        expected_mock_path_calls = [
            mock.call('http://test-uri', 'dists', 'test-archive', 'Release'),
            mock.call('chroot', 'etc/apt/preferences.d',
                      'fuel-image-name1.pref')]
        self.assertEqual(expected_mock_path_calls,
                         mock_path.join.call_args_list)

    @mock.patch.object(os, 'path')
    @mock.patch('fuel_agent.utils.build.utils.init_http_request',
                return_value=mock.Mock(text=_fake_ubuntu_release))
    def test_add_apt_preference_multuple_sections(self, mock_get, mock_path):
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            fake_sections = ['section2', 'section3']
            bu.add_apt_preference('name3', 234, 'test-archive',
                                  ' '.join(fake_sections),
                                  'chroot', 'http://test-uri')

            calls_args = [
                c[0][0] for c in file_handle_mock.write.call_args_list
            ]

            calls_package = [c for c in calls_args if c == 'Package: *\n']
            calls_pin = [c for c in calls_args if c == 'Pin: release ']
            calls_pin_p = [c for c in calls_args if c == 'Pin-Priority: 234\n']
            first_section = [
                c for c in calls_args if 'c={0}'.format(fake_sections[0]) in c
            ]
            second_section = [
                c for c in calls_args if 'c={0}'.format(fake_sections[1]) in c
            ]
            self.assertEqual(len(calls_package), 1)
            self.assertEqual(len(calls_pin), 1)
            self.assertEqual(len(calls_pin_p), 1)
            self.assertEqual(len(first_section), 0)
            self.assertEqual(len(second_section), 0)

            for pin_line in calls_args[2::4]:
                self.assertIn("l=TestLabel", pin_line)
                self.assertIn("n=testcodename", pin_line)
                self.assertIn("a=test-archive", pin_line)
                self.assertIn("o=TestOrigin", pin_line)

        expected_mock_path_calls = [
            mock.call('http://test-uri', 'dists', 'test-archive', 'Release'),
            mock.call('chroot', 'etc/apt/preferences.d',
                      'fuel-image-name3.pref')]
        self.assertEqual(expected_mock_path_calls,
                         mock_path.join.call_args_list)

    @mock.patch.object(os, 'path')
    @mock.patch('fuel_agent.utils.build.utils.init_http_request',
                return_value=mock.Mock(text=_fake_ubuntu_release))
    def test_add_apt_preference_no_sections(self, mock_get, mock_path):
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value

            bu.add_apt_preference(
                'name1',
                123,
                'test-archive',
                '',
                'chroot',
                'http://test-uri'
            )

            calls_args = [
                c[0][0] for c in file_handle_mock.write.call_args_list
            ]

            self.assertEqual(len(calls_args), 4)
            self.assertEqual(calls_args[0], 'Package: *\n')
            self.assertEqual(calls_args[1], 'Pin: release ')
            self.assertIn("l=TestLabel", calls_args[2])
            self.assertIn("n=testcodename", calls_args[2])
            self.assertIn("a=test-archive", calls_args[2])
            self.assertIn("o=TestOrigin", calls_args[2])
            self.assertNotIn("c=", calls_args[2])
            self.assertEqual(calls_args[3], 'Pin-Priority: 123\n')

        expected_mock_path_calls = [
            mock.call('http://test-uri', 'test-archive', 'Release'),
            mock.call('chroot', 'etc/apt/preferences.d',
                      'fuel-image-name1.pref')]
        self.assertEqual(expected_mock_path_calls,
                         mock_path.join.call_args_list)

    @mock.patch.object(bu, 'clean_apt_settings')
    @mock.patch.object(os, 'path')
    def test_pre_apt_get(self, mock_path, mock_clean):
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            bu.pre_apt_get('chroot', allow_unsigned_file='fake_unsigned',
                           force_ipv4_file='fake_force_ipv4',
                           pipeline_depth_file='fake_pipeline_depth',
                           install_rule_file='fake_install_rule')
            expected_calls = [
                mock.call('APT::Get::AllowUnauthenticated 1;\n'),
                mock.call('Acquire::ForceIPv4 "true";\n'),
                mock.call('Acquire::http::Pipeline-Depth 0;\n'),
                mock.call('APT::Install-Recommends "false";\n'),
                mock.call('APT::Install-Suggests "false";\n')]
            self.assertEqual(expected_calls,
                             file_handle_mock.write.call_args_list)
        mock_clean.assert_called_once_with(
            'chroot',
            allow_unsigned_file='fake_unsigned',
            force_ipv4_file='fake_force_ipv4',
            pipeline_depth_file='fake_pipeline_depth',
            install_rule_file='fake_install_rule')
        expected_join_calls = [
            mock.call('chroot', 'etc/apt/apt.conf.d',
                      'fake_unsigned'),
            mock.call('chroot', 'etc/apt/apt.conf.d',
                      'fake_force_ipv4'),
            mock.call('chroot', 'etc/apt/apt.conf.d',
                      'fake_pipeline_depth'),
            mock.call('chroot', 'etc/apt/apt.conf.d',
                      'fake_install_rule'),
            mock.call('chroot', 'etc/apt/apt.conf.d',
                      'fake_install_rule')]
        self.assertEqual(expected_join_calls, mock_path.join.call_args_list)

    @mock.patch.object(bu.utils, 'execute')
    def test_populate_basic_dev(self, mock_execute):
        bu.populate_basic_dev('fake_chroot')
        expected_execute_calls = [
            mock.call('chroot', 'fake_chroot', 'rm', '-fr', '/dev/fd'),
            mock.call('chroot', 'fake_chroot', 'ln', '-s', '/proc/self/fd',
                      '/dev/fd'),
        ]
        self.assertEqual(expected_execute_calls, mock_execute.call_args_list)

    @mock.patch('gzip.open')
    @mock.patch.object(os, 'remove')
    def test_containerize_gzip(self, mock_remove, mock_gzip):
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            file_handle_mock.read.side_effect = ['test data', '']
            g = mock.Mock()
            mock_gzip.return_value = g
            self.assertEqual('file.gz', bu.containerize('file', 'gzip', 1))
            g.write.assert_called_once_with('test data')
            expected_calls = [mock.call(1), mock.call(1)]
            self.assertEqual(expected_calls,
                             file_handle_mock.read.call_args_list)
        mock_remove.assert_called_once_with('file')

    def test_containerize_bad_container(self):
        self.assertRaises(errors.WrongImageDataError, bu.containerize, 'file',
                          'fake')

    @mock.patch('fuel_agent.utils.build.get_free_loop_device')
    @mock.patch('fuel_agent.utils.build.attach_file_to_loop')
    def test_do_build_image_retries_attach_image_max_attempts_exceeded(
            self, mock_attach_file, mock_get_free_loop_device):

        mock_attach_file.side_effect = errors.ProcessExecutionError()

        with self.assertRaises(errors.NoFreeLoopDevices):
            bu.attach_file_to_free_loop_device(
                mock.sentinel, max_loop_devices_count=255,
                loop_device_major_number=7, max_attempts=3)

        self.assertEqual(mock_attach_file.call_count, 3)

    @mock.patch('fuel_agent.utils.build.get_free_loop_device')
    @mock.patch('fuel_agent.utils.build.attach_file_to_loop')
    def test_do_build_image_retries_attach_image(
            self, mock_attach_file, mock_get_free_loop_device):

        mock_attach_file.side_effect = \
            [errors.ProcessExecutionError(),
             errors.ProcessExecutionError(),
             True]
        free_loop_device = '/dev/loop0'
        mock_get_free_loop_device.return_value = free_loop_device
        loop_device_major_number = 7
        max_loop_devices_count = 255
        max_attempts = 3
        filename = mock.sentinel

        loop_device = bu.attach_file_to_free_loop_device(
            filename, max_loop_devices_count=max_loop_devices_count,
            loop_device_major_number=loop_device_major_number,
            max_attempts=max_attempts)

        self.assertEqual(free_loop_device, loop_device)
        self.assertEqual(
            [mock.call(loop_device_major_number=loop_device_major_number,
                       max_loop_devices_count=max_loop_devices_count)] * 3,
            mock_get_free_loop_device.call_args_list)
        self.assertEqual(
            [mock.call(filename, '/dev/loop0')] * 3,
            mock_attach_file.call_args_list)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    def test_rsync_inject(self, mock_exec, mock_makedirs):
        src = 'host1:/folder1'
        dst = 'host2:/folder2'
        bu.rsync_inject(src, dst)
        mock_exec.assert_called_once_with('rsync', '-rlptDKv', src + '/',
                                          dst + '/', logged=True)

    @mock.patch('fuel_agent.utils.build.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(os, 'path', return_value=True)
    @mock.patch('fuel_agent.utils.build.yaml.load', return_value={'test': 22})
    @mock.patch('fuel_agent.utils.build.yaml.safe_dump')
    def test_dump_runtime_uuid(self, mock_open, mock_makedirs_if_not_exists,
                               mock_os, mock_load_yaml, mock_safe_dump_yaml):
        uuid = "8"
        config = "/tmp/test.conf"
        bu.dump_runtime_uuid(uuid, config)
        mock_open.assert_called_with({'runtime_uuid': '8', 'test': 22},
                                     stream=mock.ANY,
                                     encoding='utf-8')

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(os.path, 'isfile',
                       side_effect=[True, True, True, True])
    @mock.patch.object(shutil, 'copy')
    def test_propagate_host_resolv_conf(self, mock_copy, mock_path,
                                        mock_makedirs):
        bu.propagate_host_resolv_conf('/test/path')
        expected_args = [mock.call('/test/path/etc/resolv.conf',
                                   '/test/path/etc/resolv.conf.bak'),
                         mock.call('/etc/resolv.conf',
                                   '/test/path/etc/resolv.conf'),
                         mock.call('/test/path/etc/hosts',
                                   '/test/path/etc/hosts.bak'),
                         mock.call('/etc/hosts',
                                   '/test/path/etc/hosts')]
        self.assertEqual(mock_copy.call_args_list, expected_args)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(os.path, 'isfile', side_effect=[True, True])
    @mock.patch.object(shutil, 'move')
    def test_restore_host_resolv_conf(self, mock_move, mock_path,
                                      mock_makedirs):
        bu.restore_resolv_conf('/test/path')
        expected_args = [mock.call('/test/path/etc/resolv.conf.bak',
                                   '/test/path/etc/resolv.conf'),
                         mock.call('/test/path/etc/hosts.bak',
                                   '/test/path/etc/hosts')]
        self.assertEqual(mock_move.call_args_list, expected_args)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    @mock.patch('fuel_agent.utils.build.uuid.uuid4', return_value='fake_uuid')
    def test_make_targz(self, mock_uuid, mock_exec, mock_makedirs):
        self.assertEqual(bu.make_targz('/test/path'), 'fake_uuid.tar.gz')
        mock_exec.assert_called_with('tar', '-czf', 'fake_uuid.tar.gz',
                                     '--directory', '/test/path', '.',
                                     logged=True)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    def test_make_targz_with_name(self, mock_exec, mock_makedirs):
        self.assertEqual(bu.make_targz('/test/path', 'testname'), 'testname')
        mock_exec.assert_called_with('tar', '-czf', 'testname', '--directory',
                                     '/test/path', '.', logged=True)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(os.path, 'isdir', return_value=True)
    @mock.patch.object(shutil, 'copy')
    @mock.patch.object(os, 'chmod')
    def test_run_script_in_chroot(self, mock_chmod, mock_copy, mock_isdir,
                                  mock_exec, mock_makedirs):
        bu.run_script_in_chroot('/test/path', 'script_name')
        mock_exec.assert_called_with('chroot', '/test/path', '/bin/bash',
                                     '-c', '/script_name', logged=True)

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(bu, 'remove_files')
    @mock.patch('fuel_agent.utils.build.glob.glob', return_value=[])
    @mock.patch('fuel_agent.utils.build.os', environ={})
    def test_recompress_initramfs(self, mock_os, mock_glob, mock_rm_files,
                                  mock_exec):
        bu.recompress_initramfs('/test/path')
        mock_rm_files.assert_called_with('/', [])
        mock_exec.assert_called_with(
            'chroot', '/test/path',
            'update-initramfs -v -c -k all',
            logged=True,
            env_variables={'TMP': '/tmp', 'TMPDIR': '/tmp'}
        )

    @mock.patch.object(utils, 'execute')
    def test_get_installed_packages(self, mock_exec):
        mock_exec.return_value = 'virt-what 1.11-1;;vlan 1.9-3ubuntu6;;'\
                                 'watchdog 5.11-1', None
        expected_packages = {'watchdog': '5.11-1',
                             'vlan': '1.9-3ubuntu6',
                             'virt-what': '1.11-1'}
        packages = bu.get_installed_packages('/test/path')
        self.assertEqual(expected_packages, packages)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    @mock.patch('fuel_agent.utils.build.glob.glob')
    @mock.patch.object(shutil, 'copy')
    def test_copy_kernel_initramfs(self, mock_copy, mock_glob, mock_exec,
                                   mock_makedirs):
        global_return_hash = {'/test/path/boot/vmlinuz*': ['testfile1'],
                              '/test/path/boot/initrd*': ['testfile2']}
        mock_glob.side_effect = lambda x: global_return_hash[x]
        bu.copy_kernel_initramfs('/test/path', '/test/dst/dir')
        expected_copy_calls = [
            mock.call('testfile1', '/test/dst/dir/vmlinuz'),
            mock.call('testfile2', '/test/dst/dir/initrd.img')
        ]
        self.assertItemsEqual(expected_copy_calls, mock_copy.call_args_list)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    @mock.patch('fuel_agent.utils.build.glob.glob')
    @mock.patch.object(shutil, 'copy')
    @mock.patch.object(bu, 'remove_files')
    def test_copy_kernel_initramfs_with_remove(self, mock_rm, mock_copy,
                                               mock_glob, mock_exec,
                                               mock_makedirs):
        global_return_hash = {'/test/path/boot/vmlinuz*': ['testfile1'],
                              '/test/path/boot/initrd*': ['testfile2']}
        mock_glob.side_effect = lambda x: global_return_hash[x]
        bu.copy_kernel_initramfs('/test/path', '/test/dst/dir', True)
        expected_copy_calls = [
            mock.call('testfile1', '/test/dst/dir/vmlinuz'),
            mock.call('testfile2', '/test/dst/dir/initrd.img')
        ]
        expected_rm_calls = [
            mock.call('/', ['testfile1']),
            mock.call('/', ['testfile2'])
        ]
        self.assertItemsEqual(expected_copy_calls, mock_copy.call_args_list)
        self.assertItemsEqual(expected_rm_calls, mock_rm.call_args_list)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(shutil, 'move')
    @mock.patch('fuel_agent.utils.build.fu.mount_fs')
    @mock.patch('fuel_agent.utils.build.fu.umount_fs')
    @mock.patch.object(bu, 'stop_chrooted_processes')
    @mock.patch('fuel_agent.utils.build.uuid.uuid4', return_value='fake_uuid')
    def test_run_mksquashfs(self, mock_uuid, mock_stop_proc, mock_umount,
                            mock_mount, mock_move, mock_exec, mock_makedirs):
        bu.run_mksquashfs('/test/dst/dir')
        expected_mount_args = [
            mock.call('tmpfs', 'mnt_.mksquashfs.tmp.fake_uuid',
                      '/test/dst/dir/mnt',
                      'rw,nodev,nosuid,noatime,mode=0755,size=4M'),
            mock.call(None, '/test/dst/dir', '/test/dst/dir/mnt/src',
                      opts='bind'),
            mock.call(None, None, '/test/dst/dir/mnt/src', 'remount,bind,ro'),
            mock.call(None, '', '/test/dst/dir/mnt/dst', opts='bind')
        ]
        self.assertEqual(expected_mount_args, mock_mount.call_args_list)
        expected_umount_args = [
            mock.call('/test/dst/dir/mnt/dst'),
            mock.call('/test/dst/dir/mnt/src'),
            mock.call('/test/dst/dir/mnt')
        ]
        self.assertEqual(expected_umount_args, mock_umount.call_args_list)
        expected_exec_args = [
            mock.call('chroot', '/test/dst/dir', 'mksquashfs', '/mnt/src',
                      '/mnt/dst/.mksquashfs.tmp.fake_uuid', '-comp', 'xz',
                      '-no-progress', '-noappend', logged=True)
        ]
        self.assertEqual(expected_exec_args, mock_exec.call_args_list)

    @mock.patch.object(utils, 'makedirs_if_not_exists')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(shutil, 'move')
    @mock.patch('fuel_agent.utils.build.fu.mount_fs')
    @mock.patch('fuel_agent.utils.build.fu.umount_fs')
    @mock.patch.object(bu, 'stop_chrooted_processes')
    @mock.patch('fuel_agent.utils.build.uuid.uuid4', return_value='fake_uuid')
    def test_run_mksquashfs_with_name(self, mock_uuid, mock_stop_proc,
                                      mock_umount, mock_mount, mock_move,
                                      mock_exec, mock_makedirs):
        bu.run_mksquashfs('/test/dst/dir', output_name='myname')
        mock_move.assert_called_with(
            '/test/dst/dir/mnt/dst/.mksquashfs.tmp.fake_uuid',
            'myname'
        )

    @mock.patch.object(utils, 'execute')
    def test_get_config_value(self, mock_exec):
        mock_exec.return_value = [r'foo=42', '']
        self.assertEqual(42, bu.get_lvm_config_value('fake_chroot',
                                                     'section', 'foo'))

        mock_exec.return_value = [r'bar=0.5', '']
        self.assertEqual(0.5, bu.get_lvm_config_value('fake_chroot',
                                                      'section', 'bar'))

        mock_exec.return_value = [r'buzz="spam"', '']
        self.assertEqual("spam", bu.get_lvm_config_value('fake_chroot',
                                                         'section', 'buzz'))

        mock_exec.return_value = [r'list=[1, 2.3, 4., .5, "6", "7", "8"]', '']
        self.assertEqual([1, 2.3, 4., .5, "6", "7", "8"],
                         bu.get_lvm_config_value('fake_chroot',
                                                 'section', 'list'))

        mock_exec.return_value = [r'ist2=["1", "spam egg", '
                                  r'"^kind\of\regex?[.$42]"]', '']
        self.assertEqual(["1", "spam egg", r"^kind\of\regex?[.$42]"],
                         bu.get_lvm_config_value('fake_chroot',
                                                 'section', 'list2'))

    def test_update_raw_config(self):
        RAW_CONFIG = '''
foo {
\tbar=42
}'''
        self.assertEqual('''
foo {
\tbar=1
}''', bu._update_option_in_lvm_raw_config('foo', 'bar', 1, RAW_CONFIG))
        self.assertEqual('''
foo {
\tbar=42
\tbuzz=1
}''', bu._update_option_in_lvm_raw_config('foo', 'buzz', 1, RAW_CONFIG))
        self.assertEqual('''
foo {
\tbar=42
}
spam {
\tegg=1
}''', bu._update_option_in_lvm_raw_config('spam', 'egg', 1, RAW_CONFIG))
        self.assertEqual('''
foo {
\tbar=[1, 2.3, "foo", "buzz"]
}''', bu._update_option_in_lvm_raw_config('foo', 'bar',
                                          [1, 2.3, "foo", "buzz"],
                                          RAW_CONFIG))

    @mock.patch.object(time, 'strftime', return_value='fake_timestamp')
    @mock.patch.object(os, 'remove')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(bu, '_update_option_in_lvm_raw_config')
    @mock.patch.object(shutil, 'copy')
    @mock.patch.object(shutil, 'move')
    def test_override_config_value(self, m_move, m_copy, m_upd, m_execute,
                                   m_remove, m_time):
        m_execute.side_effect = (['old_fake_config', ''],
                                 ['fake_config', ''])
        m_upd.return_value = 'fake_config'
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            bu.override_lvm_config_value('fake_chroot',
                                         'foo', 'bar', 'buzz', 'lvm.conf')
        file_handle_mock.write.assert_called_with('fake_config')
        m_upd.assert_called_once_with('foo', 'bar', 'buzz', 'old_fake_config')
        m_copy.assert_called_once_with(
            'fake_chroot/lvm.conf',
            'fake_chroot/lvm.conf.bak.fake_timestamp')

    @mock.patch.object(time, 'strftime', return_value='fake_timestamp')
    @mock.patch.object(os, 'remove')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(bu, '_update_option_in_lvm_raw_config')
    @mock.patch.object(shutil, 'copy')
    @mock.patch.object(shutil, 'move')
    def test_override_config_value_fail(self, m_move, m_copy, m_upd, m_execute,
                                        m_remove, m_time):
        m_execute.side_effect = (['old_fake_config', ''],
                                 errors.ProcessExecutionError())
        m_upd.return_value = 'fake_config'
        with mock.patch('six.moves.builtins.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            self.assertRaises(errors.ProcessExecutionError,
                              bu.override_lvm_config_value,
                              'fake_chroot', 'foo', 'bar', 'buzz', 'lvm.conf')
        self.assertTrue(file_handle_mock.write.called)
        m_copy.assert_called_once_with(
            'fake_chroot/lvm.conf',
            'fake_chroot/lvm.conf.bak.fake_timestamp')
        m_move.assert_called_once_with(
            'fake_chroot/lvm.conf.bak.fake_timestamp',
            'fake_chroot/lvm.conf')

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(bu, 'override_lvm_config_value')
    def test_override_config(self, m_override_config, m_execute,):
        bu.override_lvm_config('fake_chroot',
                               {'foo': {'bar': ['fake1', 'fake2']}},
                               lvm_conf_path='/etc/lvm/lvm.conf',
                               update_initramfs=True)
        m_override_config.assert_called_once_with(
            'fake_chroot',
            'foo', 'bar',
            ['fake1', 'fake2'],
            '/etc/lvm/lvm.conf')
        m_execute.assert_called_once_with(
            'chroot', 'fake_chroot', 'update-initramfs -v -u -k all')

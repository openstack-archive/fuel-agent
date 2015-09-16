# Copyright 2014 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
import unittest2

from fuel_agent import errors
from fuel_agent.utils import fs as fu
from fuel_agent.utils import utils


@mock.patch.object(utils, 'execute')
class TestFSUtils(unittest2.TestCase):

    def test_make_xfs_add_f_flag(self, mock_exec):
        fu.make_fs('xfs', '--other-options --passed', '', '/dev/fake')
        expected_calls = [
            mock.call('mkfs.xfs', '--other-options', '--passed',
                      '-f', '/dev/fake'),
            mock.call('blkid', '-c', '/dev/null', '-o', 'value',
                      '-s', 'UUID', '/dev/fake')
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_make_xfs_empty_options(self, mock_exec):
        fu.make_fs('xfs', '', '', '/dev/fake')
        expected_calls = [
            mock.call('mkfs.xfs', '-f', '/dev/fake'),
            mock.call('blkid', '-c', '/dev/null', '-o', 'value',
                      '-s', 'UUID', '/dev/fake')
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_make_fs(self, mock_exec):
        fu.make_fs('ext4', '-F', 'fake_label', '/dev/fake')
        expected_calls = [
            mock.call('mkfs.ext4', '-F', '-L', 'fake_label', '/dev/fake'),
            mock.call('blkid', '-c', '/dev/null', '-o', 'value',
                      '-s', 'UUID', '/dev/fake')
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_make_fs_swap(self, mock_exec):
        fu.make_fs('swap', '', 'fake_label', '/dev/fake')
        expected_calls = [
            mock.call('mkswap', '-f', '-L', 'fake_label', '/dev/fake'),
            mock.call('blkid', '-c', '/dev/null', '-o', 'value',
                      '-s', 'UUID', '/dev/fake')
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_extend_fs_ok_ext2(self, mock_exec):
        fu.extend_fs('ext2', '/dev/fake')
        expected_calls = [
            mock.call('e2fsck', '-yf', '/dev/fake', check_exit_code=[0]),
            mock.call('resize2fs', '/dev/fake', check_exit_code=[0]),
            mock.call('e2fsck', '-pf', '/dev/fake', check_exit_code=[0])
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_extend_fs_ok_ext3(self, mock_exec):
        fu.extend_fs('ext3', '/dev/fake')
        expected_calls = [
            mock.call('e2fsck', '-yf', '/dev/fake', check_exit_code=[0]),
            mock.call('resize2fs', '/dev/fake', check_exit_code=[0]),
            mock.call('e2fsck', '-pf', '/dev/fake', check_exit_code=[0])
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_extend_fs_ok_ext4(self, mock_exec):
        fu.extend_fs('ext4', '/dev/fake')
        expected_calls = [
            mock.call('e2fsck', '-yf', '/dev/fake', check_exit_code=[0]),
            mock.call('resize2fs', '/dev/fake', check_exit_code=[0]),
            mock.call('e2fsck', '-pf', '/dev/fake', check_exit_code=[0])
        ]
        self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_extend_fs_ok_xfs(self, mock_exec):
        fu.extend_fs('xfs', '/dev/fake')
        mock_exec.assert_called_once_with(
            'xfs_growfs', '/dev/fake', check_exit_code=[0])

    def test_extend_fs_unsupported_fs(self, mock_exec):
        self.assertRaises(errors.FsUtilsError, fu.extend_fs,
                          'unsupported', '/dev/fake')

    def test_mount_fs(self, mock_exec):
        fu.mount_fs('ext3', '/dev/fake', '/target')
        mock_exec.assert_called_once_with(
            'mount', '-t', 'ext3', '/dev/fake', '/target', check_exit_code=[0])

    def test_mount_bind_no_path2(self, mock_exec):
        fu.mount_bind('/target', '/fake')
        mock_exec.assert_called_once_with(
            'mount', '--bind', '/fake', '/target/fake', check_exit_code=[0])

    def test_mount_bind_path2(self, mock_exec):
        fu.mount_bind('/target', '/fake', '/fake2')
        mock_exec.assert_called_once_with(
            'mount', '--bind', '/fake', '/target/fake2', check_exit_code=[0])

    def test_umount_fs_ok(self, mock_exec):
        fu.umount_fs('/fake')
        expected_calls = [
            mock.call('mountpoint', '-q', '/fake', check_exit_code=[0]),
            mock.call('umount', '/fake', check_exit_code=[0])
        ]
        self.assertEqual(expected_calls, mock_exec.call_args_list)

    def test_umount_fs_not_mounted(self, mock_exec):
        mock_exec.side_effect = errors.ProcessExecutionError
        fu.umount_fs('/fake')
        mock_exec.assert_called_once_with(
            'mountpoint', '-q', '/fake', check_exit_code=[0])

    def test_umount_fs_error(self, mock_exec):
        mock_exec.side_effect = [
            None, errors.ProcessExecutionError('message'), ('', '')]
        fu.umount_fs('/fake', try_lazy_umount=True)
        expected_calls = [
            mock.call('mountpoint', '-q', '/fake', check_exit_code=[0]),
            mock.call('umount', '/fake', check_exit_code=[0]),
            mock.call('umount', '-l', '/fake', check_exit_code=[0])
        ]
        self.assertEqual(expected_calls, mock_exec.call_args_list)

    def test_umount_fs_error_lazy_false(self, mock_exec):
        mock_exec.side_effect = [
            None, errors.ProcessExecutionError('message')]
        expected_calls = [
            mock.call('mountpoint', '-q', '/fake', check_exit_code=[0]),
            mock.call('umount', '/fake', check_exit_code=[0]),
        ]
        self.assertRaises(errors.ProcessExecutionError,
                          fu.umount_fs, '/fake', try_lazy_umount=False)
        self.assertEqual(expected_calls, mock_exec.call_args_list)

    def test_format_fs_label(self, _):
        short_label = 'label'
        long_label = '0123456789ABCD'
        long_label_trimmed = long_label[:12]
        template = ' -L {0} '

        self.assertEqual(fu.format_fs_label(None), '')

        self.assertEqual(fu.format_fs_label(short_label),
                         template.format(short_label))

        self.assertEqual(fu.format_fs_label(long_label),
                         template.format(long_label_trimmed))

    def test_get_fs_type(self, mock_exec):
        output = "megafs\n"
        mock_exec.return_value = (output, '')
        ret = fu.get_fs_type('/dev/sda4')
        mock_exec.assert_called_once_with('blkid', '-o', 'value',
                                          '-s', 'TYPE', '-c', '/dev/null',
                                          '/dev/sda4')
        self.assertEqual(ret, 'megafs')

    @mock.patch('fuel_agent.utils.fs.mount_fs')
    @mock.patch('fuel_agent.utils.fs.tempfile.mkdtemp')
    def test_mount_fs_temp(self, mock_mkdtemp, mock_mount, mock_exec):
        mock_mkdtemp.return_value = '/tmp/dir'
        self.assertEqual('/tmp/dir', fu.mount_fs_temp('ext4', '/dev/fake'))
        mock_mkdtemp.assert_called_once_with(dir=None, suffix='')
        mock_mount.assert_called_once_with('ext4', '/dev/fake', '/tmp/dir')


class TestFSRetry(unittest2.TestCase):

    def test_make_fs_bad_swap_retry(self):
        # We mock utils.execute to throw an exception on first two
        # invocations of blkid to test the retry loop.
        rvs = [
            None, errors.ProcessExecutionError(),
            None, errors.ProcessExecutionError(),
            None, None
        ]
        with mock.patch.object(utils, 'execute', side_effect=rvs) as mock_exec:
            fu.make_fs('swap', '', 'fake_label', '/dev/fake')
            expected_calls = 3 * [
                mock.call('mkswap', '-f', '-L', 'fake_label', '/dev/fake'),
                mock.call('blkid', '-c', '/dev/null', '-o', 'value',
                          '-s', 'UUID', '/dev/fake')
            ]
            self.assertEqual(mock_exec.call_args_list, expected_calls)

    def test_make_fs_bad_swap_failure(self):
        # We mock utils.execute to throw an exception on invocations
        # of blkid (MAX_MKFS_TRIES times) to see if it fails.
        rvs = fu.MAX_MKFS_TRIES * [None, errors.ProcessExecutionError()]
        with mock.patch.object(utils, 'execute', side_effect=rvs) as mock_exec:
            with self.assertRaises(errors.FsUtilsError):
                fu.make_fs('swap', '', 'fake_label', '/dev/fake')
                expected_calls = 3 * [
                    mock.call('mkswap', '-f', '-L', 'fake_label', '/dev/fake'),
                    mock.call('blkid', '-c', '/dev/null', '-o', 'value',
                              '-s', 'UUID', '/dev/fake')
                ]
                self.assertEqual(mock_exec.call_args_list, expected_calls)

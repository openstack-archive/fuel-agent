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

import copy
import os
import signal

from oslo_config import cfg
import six
import unittest2

from fuel_agent.drivers import nailgun
from fuel_agent import errors
from fuel_agent import manager
from fuel_agent import objects
from fuel_agent.tests import test_nailgun
from fuel_agent.utils import artifact as au
from fuel_agent.utils import fs as fu
from fuel_agent.utils import hardware as hu
from fuel_agent.utils import lvm as lu
from fuel_agent.utils import md as mu
from fuel_agent.utils import partition as pu
from fuel_agent.utils import utils

if six.PY2:
    import mock
elif six.PY3:
    import unittest.mock as mock

CONF = cfg.CONF


class FakeChain(object):
    processors = []

    def append(self, thing):
        self.processors.append(thing)

    def process(self):
        pass


class TestManager(unittest2.TestCase):

    @mock.patch('fuel_agent.drivers.nailgun.Nailgun.parse_image_meta',
                return_value={})
    @mock.patch.object(hu, 'list_block_devices')
    def setUp(self, mock_lbd, mock_image_meta):
        super(TestManager, self).setUp()
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        self.mgr = manager.Manager(test_nailgun.PROVISION_SAMPLE_DATA)

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub1_kernel_initrd_guessed(self, mock_umount,
                                                       mock_mount, mock_utils,
                                                       mock_gu, mock_open,
                                                       mock_bu, mock_hw,
                                                       mock_prov):
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('', '')
        mock_gu.guess_grub_version.return_value = 1
        # grub has kernel_name and initrd_name both set to None
        self.mgr.driver.grub.kernel_name = None
        self.mgr.driver.grub.initrd_name = None
        self.mgr.driver.grub.kernel_params = 'fake_kernel_params'
        self.mgr.driver.grub.kernel_regexp = 'fake_kernel_regexp'
        self.mgr.driver.grub.initrd_regexp = 'fake_initrd_regexp'
        mock_gu.guess_kernel.return_value = 'guessed_kernel'
        mock_gu.guess_initrd.return_value = 'guessed_initrd'
        self.mgr.do_bootloader()
        self.assertFalse(mock_gu.grub2_cfg.called)
        self.assertFalse(mock_gu.grub2_install.called)
        mock_gu.grub1_cfg.assert_called_once_with(
            kernel_params='fake_kernel_params',
            initrd='guessed_initrd', kernel='guessed_kernel',
            chroot='/tmp/target', grub_timeout=10)
        mock_gu.grub1_install.assert_called_once_with(
            ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            '/dev/sda3', chroot='/tmp/target')
        mock_gu.guess_initrd.assert_called_once_with(
            regexp='fake_initrd_regexp', chroot='/tmp/target')
        mock_gu.guess_kernel.assert_called_once_with(
            regexp='fake_kernel_regexp', chroot='/tmp/target')

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub1_kernel_initrd_set(self, mock_umount,
                                                   mock_mount, mock_utils,
                                                   mock_gu, mock_open,
                                                   mock_bu, mock_hw,
                                                   mock_prov):
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('', '')
        mock_gu.guess_grub_version.return_value = 1
        self.mgr.driver.grub.kernel_params = 'fake_kernel_params'
        # grub has kernel_name and initrd_name set
        self.mgr.driver.grub.kernel_name = 'kernel_name'
        self.mgr.driver.grub.initrd_name = 'initrd_name'
        self.mgr.do_bootloader()
        self.assertFalse(mock_gu.grub2_cfg.called)
        self.assertFalse(mock_gu.grub2_install.called)
        mock_gu.grub1_cfg.assert_called_once_with(
            kernel_params='fake_kernel_params',
            initrd='initrd_name', kernel='kernel_name', chroot='/tmp/target',
            grub_timeout=10)
        mock_gu.grub1_install.assert_called_once_with(
            ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            '/dev/sda3', chroot='/tmp/target')
        self.assertFalse(mock_gu.guess_initrd.called)
        self.assertFalse(mock_gu.guess_kernel.called)
        self.assertFalse(mock_bu.override_lvm_config.called)

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.objects.bootloader.Grub', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_rootfs_uuid(self, mock_umount, mock_mount,
                                       mock_utils, mock_gu, mock_open,
                                       mock_grub, mock_bu, mock_hw, mock_prov):
        def _fake_uuid(*args, **kwargs):
            if len(args) >= 8 and args[7] == '/dev/mapper/os-root':
                return ('FAKE_ROOTFS_UUID', None)
            else:
                return ('FAKE_UUID', None)
        CONF.use_uuid_root = True
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.side_effect = _fake_uuid
        mock_grub.version = 2
        mock_gu.guess_grub_version.return_value = 2
        mock_grub.kernel_name = 'fake_kernel_name'
        mock_grub.initrd_name = 'fake_initrd_name'
        mock_grub.kernel_params = 'fake_kernel_params'
        self.mgr.driver._grub = mock_grub
        self.mgr.do_bootloader()
        mock_grub.append_kernel_params.assert_called_once_with(
            'root=UUID=FAKE_ROOTFS_UUID ')
        self.assertEqual(2, mock_grub.version)

    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    def test_do_bootloader_rootfs_not_found(self, mock_umount, mock_utils,
                                            mock_bu, mock_hw):
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('fake', 'fake')
        self.mgr.driver._partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/boot', fs_type='ext2')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='swap', fs_type='swap')
        self.assertRaises(errors.WrongPartitionSchemeError,
                          self.mgr.do_bootloader)

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub_version_changes(
            self, mock_umount, mock_mount, mock_utils, mock_gu, mock_open,
            mock_bu, mock_hw, mock_prov):
        # actually covers only grub1 related logic
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        mock_gu.guess_grub_version.return_value = 'expected_version'
        self.mgr.do_bootloader()
        mock_gu.guess_grub_version.assert_called_once_with(
            chroot='/tmp/target')
        self.assertEqual('expected_version', self.mgr.driver.grub.version)

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub1(self, mock_umount, mock_mount, mock_utils,
                                 mock_gu, mock_open, mock_bu, mock_hw,
                                 mock_prov):
        # actually covers only grub1 related logic
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        mock_gu.guess_initrd.return_value = 'guessed_initrd'
        mock_gu.guess_kernel.return_value = 'guessed_kernel'
        mock_gu.guess_grub_version.return_value = 1
        self.mgr.do_bootloader()
        mock_gu.guess_grub_version.assert_called_once_with(
            chroot='/tmp/target')
        mock_gu.grub1_cfg.assert_called_once_with(
            kernel_params=' console=ttyS0,9600 console=tty0 rootdelay=90 '
                          'nomodeset',
            initrd='guessed_initrd',
            chroot='/tmp/target',
            kernel='guessed_kernel',
            grub_timeout=10)
        mock_gu.grub1_install.assert_called_once_with(
            ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            '/dev/sda3', chroot='/tmp/target')
        self.assertFalse(mock_gu.grub2_cfg.called)
        self.assertFalse(mock_gu.grub2_install.called)

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_grub2(self, mock_umount, mock_mount, mock_utils,
                                 mock_gu, mock_open, mock_bu, mock_hw,
                                 mock_prov):
        # actually covers only grub2 related logic
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        mock_gu.guess_grub_version.return_value = 2
        self.mgr.do_bootloader()
        mock_gu.guess_grub_version.assert_called_once_with(
            chroot='/tmp/target')
        mock_gu.grub2_cfg.assert_called_once_with(
            kernel_params=' console=ttyS0,9600 console=tty0 rootdelay=90 '
                          'nomodeset',
            chroot='/tmp/target', grub_timeout=10)
        mock_gu.grub2_install.assert_called_once_with(
            ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            chroot='/tmp/target')
        self.assertFalse(mock_gu.grub1_cfg.called)
        self.assertFalse(mock_gu.grub1_install.called)

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.gu', autospec=True)
    @mock.patch('fuel_agent.manager.utils', autospec=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_with_multipath(
            self, mock_umount, mock_mount, mock_utils, mock_gu, mock_open,
            mock_bu, mock_hw, mock_prov):
        # actually covers only multipath related logic
        # Lets assume that only /dev/sda device is not-multipath
        mock_hw.is_multipath_device.side_effect = False, False, True
        mock_hw.udevreport.side_effect = (
            {'DEVLINKS': ['/dev/disk/by-id/fake1']},
            {'DEVLINKS': ['/dev/disk/by-id/fake21', '/dev/disk/by-id/fake22']}
        )
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        mock_gu.guess_grub_version.return_value = 2
        self.mgr.do_bootloader()
        mock_bu.override_lvm_config.assert_called_once_with(
            '/tmp/target',
            {'devices': {
                'scan': ['/dev/disk/', '/dev/mapper/'],
                'preferred_names': ['^/dev/mapper/'],
                'global_filter': [
                    'a|^/dev/disk/by-id/fake1(p)?(-part)?[0-9]*|',
                    'a|^/dev/disk/by-id/fake21(p)?(-part)?[0-9]*|',
                    'a|^/dev/disk/by-id/fake22(p)?(-part)?[0-9]*|',
                    'r|^/dev/disk/.*|',
                    'a|^/dev/mapper/.*|',
                    'r/.*/']}},
            update_initramfs=True,
            lvm_conf_path='/etc/lvm/lvm.conf')

    @mock.patch('fuel_agent.manager.provision', autospec=True)
    @mock.patch('fuel_agent.manager.hw', autospec=True)
    @mock.patch('fuel_agent.manager.bu', autospec=True)
    @mock.patch('fuel_agent.manager.gu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_bootloader_writes(self, mock_umount, mock_mount, mock_utils,
                                  mock_gu, mock_bu, mock_hw, mock_prov):
        # actually covers only write() calls
        mock_hw.is_multipath_device.return_value = False
        mock_utils.execute.return_value = ('fake_UUID\n', None)
        with mock.patch('fuel_agent.manager.open', create=True) as mock_open:
            file_handle_mock = mock_open.return_value.__enter__.return_value
            self.mgr.do_bootloader()
            expected_open_calls = [
                mock.call('/tmp/target/etc/nailgun-agent/nodiscover', 'w'),
                mock.call('/tmp/target/etc/fstab', 'wt', encoding='utf-8')]
            self.assertEqual(expected_open_calls, mock_open.call_args_list)
            expected_write_calls = [
                mock.call('UUID=fake_UUID /boot ext2 defaults 0 0\n'),
                mock.call('UUID=fake_UUID /tmp ext2 defaults 0 0\n'),
                mock.call(
                    'UUID=fake_UUID / ext4 defaults,errors=panic 0 0\n'),
                mock.call('UUID=fake_UUID swap swap defaults 0 0\n'),
                mock.call('UUID=fake_UUID /var/lib/glance xfs defaults 0 0\n')
            ]
            self.assertEqual(expected_write_calls,
                             file_handle_mock.write.call_args_list)
        mock_umount.assert_called_once_with('/tmp/target')
        mock_mount.assert_called_once_with('/tmp/target')
        mock_utils.makedirs_if_not_exists.assert_called_once_with(
            '/tmp/target/etc/nailgun-agent')
        mock_prov.udev_nic_naming_rules.assert_called_once_with(
            '/tmp/target', self.mgr.driver.configdrive_scheme.common.udevrules)
        mock_prov.configure_admin_nic.assert_called_once_with(
            chroot='/tmp/target',
            iface=self.mgr.driver.configdrive_scheme.common.admin_iface_name,
            ip=self.mgr.driver.configdrive_scheme.common.admin_ip,
            netmask=self.mgr.driver.configdrive_scheme.common.admin_mask,
            gw=self.mgr.driver.configdrive_scheme.common.gw)

    @mock.patch('fuel_agent.drivers.nailgun.Nailgun.parse_image_meta',
                return_value={})
    @mock.patch.object(hu, 'list_block_devices')
    @mock.patch.object(fu, 'make_fs')
    def test_do_partitioning_with_keep_data_flag(self, mock_fu_mf, mock_lbd,
                                                 mock_image_meta):
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        data = copy.deepcopy(test_nailgun.PROVISION_SAMPLE_DATA)

        for disk in data['ks_meta']['pm_data']['ks_spaces']:
            for volume in disk['volumes']:
                if volume['type'] == 'pv' and volume['vg'] == 'image':
                    volume['keep_data'] = True

        self.mgr = manager.Manager(data)

        self.mgr.do_partitioning()
        mock_fu_mf_expected_calls = [
            mock.call('ext2', '', '', '/dev/sda3'),
            mock.call('ext2', '', '', '/dev/sda4'),
            mock.call('swap', '', '', '/dev/mapper/os-swap')]
        self.assertEqual(mock_fu_mf_expected_calls, mock_fu_mf.call_args_list)

    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(manager.utils, 'blacklist_udev_rules')
    @mock.patch.object(manager.utils, 'unblacklist_udev_rules')
    @mock.patch.object(manager.utils, 'execute')
    @mock.patch.object(manager.utils, 'udevadm_trigger_blocks')
    @mock.patch.object(mu, 'mdclean_all')
    @mock.patch.object(lu, 'lvremove_all')
    @mock.patch.object(lu, 'vgremove_all')
    @mock.patch.object(lu, 'pvremove_all')
    @mock.patch.object(fu, 'make_fs')
    @mock.patch.object(lu, 'lvcreate')
    @mock.patch.object(lu, 'vgcreate')
    @mock.patch.object(lu, 'pvcreate')
    @mock.patch.object(mu, 'mdcreate')
    @mock.patch.object(pu, 'set_gpt_type')
    @mock.patch.object(pu, 'set_partition_flag')
    @mock.patch.object(pu, 'make_partition')
    @mock.patch.object(pu, 'make_label')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_partitioning_md(self, mock_hu_lbd, mock_pu_ml, mock_pu_mp,
                                mock_pu_spf, mock_pu_sgt, mock_mu_m, mock_lu_p,
                                mock_lu_v, mock_lu_l, mock_fu_mf, mock_pvr,
                                mock_vgr, mock_lvr, mock_mdr, mock_udevtrig,
                                mock_exec, mock_unbl, mock_bl, mock_os_path):
        mock_hu_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_os_path.return_value = True
        self.mgr.driver.partition_scheme.mds = [
            objects.MD('fake_md1', 'mirror', devices=['/dev/sda1',
                                                      '/dev/sdb1']),
            objects.MD('fake_md2', 'mirror', devices=['/dev/sdb3',
                                                      '/dev/sdc1']),
        ]
        self.mgr.do_partitioning()
        self.assertEqual([mock.call('fake_md1', 'mirror',
                                    ['/dev/sda1', '/dev/sdb1'], 'default'),
                          mock.call('fake_md2', 'mirror',
                                    ['/dev/sdb3', '/dev/sdc1'], 'default')],
                         mock_mu_m.call_args_list)

    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(manager.utils, 'blacklist_udev_rules')
    @mock.patch.object(manager.utils, 'unblacklist_udev_rules')
    @mock.patch.object(manager.utils, 'execute')
    @mock.patch.object(manager.utils, 'udevadm_trigger_blocks')
    @mock.patch.object(mu, 'mdclean_all')
    @mock.patch.object(lu, 'lvremove_all')
    @mock.patch.object(lu, 'vgremove_all')
    @mock.patch.object(lu, 'pvremove_all')
    @mock.patch.object(fu, 'make_fs')
    @mock.patch.object(lu, 'lvcreate')
    @mock.patch.object(lu, 'vgcreate')
    @mock.patch.object(lu, 'pvcreate')
    @mock.patch.object(mu, 'mdcreate')
    @mock.patch.object(pu, 'set_gpt_type')
    @mock.patch.object(pu, 'set_partition_flag')
    @mock.patch.object(pu, 'make_partition')
    @mock.patch.object(pu, 'make_label')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_partitioning(self, mock_hu_lbd, mock_pu_ml, mock_pu_mp,
                             mock_pu_spf, mock_pu_sgt, mock_mu_m, mock_lu_p,
                             mock_lu_v, mock_lu_l, mock_fu_mf, mock_pvr,
                             mock_vgr, mock_lvr, mock_mdr, mock_udevtrig,
                             mock_exec, mock_unbl, mock_bl, mock_os_path):
        mock_os_path.return_value = True
        mock_hu_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        self.mgr.do_partitioning()
        mock_unbl.assert_called_once_with(udev_rules_dir='/etc/udev/rules.d',
                                          udev_rename_substr='.renamedrule')
        mock_bl.assert_called_once_with(udev_rules_dir='/etc/udev/rules.d',
                                        udev_rules_lib_dir='/lib/udev/rules.d',
                                        udev_empty_rule='empty_rule',
                                        udev_rename_substr='.renamedrule')
        mock_pu_ml_expected_calls = [mock.call('/dev/sda', 'gpt'),
                                     mock.call('/dev/sdb', 'gpt'),
                                     mock.call('/dev/sdc', 'gpt')]
        self.assertEqual(mock_pu_ml_expected_calls, mock_pu_ml.call_args_list)

        mock_pu_mp_expected_calls = [
            mock.call('/dev/sda', 1, 25, 'primary', alignment='optimal'),
            mock.call('/dev/sda', 26, 226, 'primary', alignment='optimal'),
            mock.call('/dev/sda', 227, 427, 'primary', alignment='optimal'),
            mock.call('/dev/sda', 428, 628, 'primary', alignment='optimal'),
            mock.call('/dev/sda', 629, 20067, 'primary', alignment='optimal'),
            mock.call('/dev/sda', 20068, 65665, 'primary',
                      alignment='optimal'),
            mock.call('/dev/sda', 65666, 65686, 'primary',
                      alignment='optimal'),
            mock.call('/dev/sdb', 1, 25, 'primary', alignment='optimal'),
            mock.call('/dev/sdb', 26, 226, 'primary', alignment='optimal'),
            mock.call('/dev/sdb', 227, 65198, 'primary', alignment='optimal'),
            mock.call('/dev/sdc', 1, 25, 'primary', alignment='optimal'),
            mock.call('/dev/sdc', 26, 226, 'primary', alignment='optimal'),
            mock.call('/dev/sdc', 227, 65198, 'primary', alignment='optimal')]
        self.assertEqual(mock_pu_mp_expected_calls, mock_pu_mp.call_args_list)

        mock_pu_spf_expected_calls = [mock.call('/dev/sda', 1, 'bios_grub'),
                                      mock.call('/dev/sdb', 1, 'bios_grub'),
                                      mock.call('/dev/sdc', 1, 'bios_grub')]
        self.assertEqual(mock_pu_spf_expected_calls,
                         mock_pu_spf.call_args_list)

        mock_pu_sgt_expected_calls = [mock.call('/dev/sda', 4, 'fake_guid')]
        self.assertEqual(mock_pu_sgt_expected_calls,
                         mock_pu_sgt.call_args_list)

        mock_lu_p_expected_calls = [
            mock.call('/dev/sda5', metadatasize=28, metadatacopies=2),
            mock.call('/dev/sda6', metadatasize=28, metadatacopies=2),
            mock.call('/dev/sdb3', metadatasize=28, metadatacopies=2),
            mock.call('/dev/sdc3', metadatasize=28, metadatacopies=2)]
        self.assertEqual(mock_lu_p_expected_calls, mock_lu_p.call_args_list)

        mock_lu_v_expected_calls = [mock.call('os', '/dev/sda5'),
                                    mock.call('image', '/dev/sda6',
                                              '/dev/sdb3', '/dev/sdc3')]
        self.assertEqual(mock_lu_v_expected_calls, mock_lu_v.call_args_list)

        mock_lu_l_expected_calls = [mock.call('os', 'root', 15360),
                                    mock.call('os', 'swap', 4014),
                                    mock.call('image', 'glance', 175347)]
        self.assertEqual(mock_lu_l_expected_calls, mock_lu_l.call_args_list)

        mock_fu_mf_expected_calls = [
            mock.call('ext2', '', '', '/dev/sda3'),
            mock.call('ext2', '', '', '/dev/sda4'),
            mock.call('swap', '', '', '/dev/mapper/os-swap'),
            mock.call('xfs', '', '', '/dev/mapper/image-glance')]
        self.assertEqual(mock_fu_mf_expected_calls, mock_fu_mf.call_args_list)

    @mock.patch('tempfile.mkdtemp')
    @mock.patch('os.makedirs')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    def test_prepare_configdrive_files(self, mock_u_ras, mock_u_e,
                                       mock_makedirs, mock_mkdtemp):
        mock_mkdtemp.return_value = '/tmp/qwe'
        ret = self.mgr._prepare_configdrive_files()
        self.assertEqual(ret, ['/tmp/qwe/openstack'])
        mock_mkdtemp.assert_called_once_with(dir=CONF.tmp_path)
        mock_makedirs.assert_called_once_with('/tmp/qwe/openstack/latest')

        mock_u_ras_expected_calls = [
            mock.call(CONF.nc_template_path,
                      ['cloud_config_pro_fi-le.jinja2',
                       'cloud_config_pro.jinja2',
                       'cloud_config_pro_fi.jinja2',
                       'cloud_config.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'cloud_config.txt')),
            mock.call(CONF.nc_template_path,
                      ['boothook_pro_fi-le.jinja2',
                       'boothook_pro.jinja2',
                       'boothook_pro_fi.jinja2',
                       'boothook.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'boothook.txt')),
            mock.call(CONF.nc_template_path,
                      ['meta_data_json_pro_fi-le.jinja2',
                       'meta_data_json_pro.jinja2',
                       'meta_data_json_pro_fi.jinja2',
                       'meta_data_json.jinja2'],
                      mock.ANY, '/tmp/qwe/openstack/latest/meta_data.json')]
        self.assertEqual(mock_u_ras_expected_calls, mock_u_ras.call_args_list)

        mock_u_e.assert_called_once_with(
            'write-mime-multipart',
            '--output=/tmp/qwe/openstack/latest/user_data',
            '%s/%s:text/cloud-boothook' % (CONF.tmp_path, 'boothook.txt'),
            '%s/%s:text/cloud-config' % (CONF.tmp_path, 'cloud_config.txt'))

    @mock.patch('os.makedirs')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    def test_prepare_cloudinit_config(self, mock_u_ras, mock_u_e,
                                      mock_makedirs):
        self.mgr._prepare_cloudinit_config_files(
            '/var/lib/cloud/seed/nocloud')
        mock_makedirs.assert_called_once_with('/var/lib/cloud/seed/nocloud')

        mock_u_ras_expected_calls = [
            mock.call(CONF.nc_template_path,
                      ['cloud_config_pro_fi-le.jinja2',
                       'cloud_config_pro.jinja2',
                       'cloud_config_pro_fi.jinja2',
                       'cloud_config.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'cloud_config.txt')),
            mock.call(CONF.nc_template_path,
                      ['boothook_pro_fi-le.jinja2',
                       'boothook_pro.jinja2',
                       'boothook_pro_fi.jinja2',
                       'boothook.jinja2'],
                      mock.ANY, '%s/%s' % (CONF.tmp_path, 'boothook.txt')),
            mock.call(CONF.nc_template_path,
                      ['meta_data_json_pro_fi-le.jinja2',
                       'meta_data_json_pro.jinja2',
                       'meta_data_json_pro_fi.jinja2',
                       'meta_data_json.jinja2'],
                      mock.ANY, '/var/lib/cloud/seed/nocloud/meta-data')]
        self.assertEqual(mock_u_ras_expected_calls, mock_u_ras.call_args_list)

        mock_u_e.assert_called_once_with(
            'write-mime-multipart',
            '--output=/var/lib/cloud/seed/nocloud/user-data',
            '%s/%s:text/cloud-boothook' % (CONF.tmp_path, 'boothook.txt'),
            '%s/%s:text/cloud-config' % (CONF.tmp_path, 'cloud_config.txt'))

    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('os.path.isdir')
    @mock.patch('os.rmdir')
    @mock.patch('shutil.copy2')
    @mock.patch('shutil.copytree')
    @mock.patch('tempfile.mkdtemp')
    @mock.patch.object(hu, 'list_block_devices')
    @mock.patch.object(utils, 'execute')
    def test_make_configdrive_image(self, mock_u_e, mock_lbd, mock_mkdtemp,
                                    mock_copytree, mock_copy2, mock_rmdir,
                                    mock_isdir, mock_fu):
        mock_u_e.side_effect = [(' 795648', ''), None]
        mock_isdir.side_effect = [True, False]
        mock_mkdtemp.return_value = '/tmp/mount_point'
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE

        self.mgr._make_configdrive_image(['/tmp/openstack', '/tmp/somefile'])

        mock_u_e_calls = [
            mock.call('blockdev', '--getsize64', '/dev/sda7'),
            mock.call('truncate', '--size=795648', CONF.config_drive_path)]

        self.assertEqual(mock_u_e_calls, mock_u_e.call_args_list,
                         str(mock_u_e.call_args_list))

        mock_fu.make_fs.assert_called_with(fs_type='ext2',
                                           fs_options=' -b 4096 -F ',
                                           fs_label='config-2',
                                           dev=CONF.config_drive_path)
        mock_fu.mount_fs.assert_called_with('ext2',
                                            CONF.config_drive_path,
                                            '/tmp/mount_point')
        mock_fu.umount_fs.assert_called_with('/tmp/mount_point')
        mock_rmdir.assert_called_with('/tmp/mount_point')
        mock_copy2.assert_called_with('/tmp/somefile', '/tmp/mount_point')
        mock_copytree.assert_called_with('/tmp/openstack',
                                         '/tmp/mount_point/openstack')

    @mock.patch.object(fu, 'get_fs_type')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch.object(hu, 'list_block_devices')
    def test_add_configdrive_image(self, mock_lbd, mock_getsize,
                                   mock_calc_md5, mock_get_fs_type):
        mock_get_fs_type.return_value = 'ext999'
        mock_calc_md5.return_value = 'fakemd5'
        mock_getsize.return_value = 123
        self.mgr._add_configdrive_image()

        self.assertEqual(2, len(self.mgr.driver.image_scheme.images))
        cf_drv_img = self.mgr.driver.image_scheme.images[-1]
        self.assertEqual('file://%s' % CONF.config_drive_path, cf_drv_img.uri)
        self.assertEqual('/dev/sda7', cf_drv_img.target_device)
        self.assertEqual('ext999', cf_drv_img.format)
        self.assertEqual('raw', cf_drv_img.container)
        self.assertEqual('fakemd5', cf_drv_img.md5)
        self.assertEqual(123, cf_drv_img.size)

    @mock.patch.object(objects.PartitionScheme, 'configdrive_device')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch.object(hu, 'list_block_devices')
    def test_add_configdrive_image_no_configdrive_device(self, mock_lbd,
                                                         mock_getsize,
                                                         mock_calc_md5,
                                                         mock_p_ps_cd):
        mock_calc_md5.return_value = 'fakemd5'
        mock_getsize.return_value = 123
        mock_p_ps_cd.return_value = None
        self.assertRaises(errors.WrongPartitionSchemeError,
                          self.mgr._add_configdrive_image)

    def test_do_configdrive(self):
        with mock.patch.multiple(self.mgr,
                                 _prepare_configdrive_files=mock.DEFAULT,
                                 _make_configdrive_image=mock.DEFAULT,
                                 _add_configdrive_image=mock.DEFAULT) as mocks:
            mocks['_prepare_configdrive_files'].return_value = 'x'
            self.mgr.do_configdrive()
            mocks['_prepare_configdrive_files'].assert_called_once_with()
            mocks['_make_configdrive_image'].assert_called_once_with('x')
            mocks['_add_configdrive_image'].assert_called_once_with()

    @mock.patch('fuel_agent.manager.Manager.move_files_to_their_places')
    @mock.patch.object(fu, 'get_fs_type')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(hu, 'is_block_device')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage(self, mock_lbd, mock_u_ras, mock_u_e, mock_au_c,
                          mock_au_h, mock_au_l, mock_au_g, mock_fu_ef,
                          mock_http_req, mock_yaml, mock_get_size, mock_md5,
                          mock_ibd, mock_os_path, mock_get_fs_type,
                          mock_mfttp):
        mock_os_path.return_value = True
        mock_ibd.return_value = True
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr._add_configdrive_image()
        self.mgr.do_copyimage()
        imgs = self.mgr.driver.image_scheme.images
        self.assertEqual(2, len(imgs))
        expected_processors_list = []
        for img in imgs[:-1]:
            expected_processors_list += [
                img.uri,
                au.HttpUrl,
                au.GunzipStream,
                img.target_device
            ]
        expected_processors_list += [
            imgs[-1].uri,
            au.LocalFile,
            imgs[-1].target_device
        ]
        self.assertEqual(expected_processors_list,
                         mock_au_c.return_value.processors)
        mock_fu_ef_expected_calls = [
            mock.call('ext4', '/dev/mapper/os-root')]
        self.assertEqual(mock_fu_ef_expected_calls, mock_fu_ef.call_args_list)
        self.assertTrue(mock_mfttp.called)

    @mock.patch('fuel_agent.manager.Manager.inject_cloudinit_config')
    @mock.patch('fuel_agent.manager.Manager.move_files_to_their_places')
    @mock.patch('fuel_agent.manager.CONF.use_configdrive', False)
    def test_cloudconfig_iinjection(self, mock_mfttp, mock_icc):
        with mock.patch.object(self.mgr.driver.image_scheme, 'images', []):
            self.mgr.do_copyimage()
        mock_icc.assert_called_once_with()

    @mock.patch.object(fu, 'get_fs_type')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(hu, 'is_block_device')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage_target_doesnt_exist(self, mock_lbd, mock_u_ras,
                                              mock_u_e, mock_au_c, mock_au_h,
                                              mock_au_l, mock_au_g, mock_fu_ef,
                                              mock_http_req, mock_yaml,
                                              mock_get_size, mock_md5,
                                              mock_ibd, mock_os_path,
                                              mock_get_fs_type):
        mock_os_path.return_value = False
        mock_ibd.return_value = True
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr._add_configdrive_image()
        with self.assertRaisesRegexp(errors.WrongDeviceError,
                                     'TARGET processor .* does not exist'):
            self.mgr.do_copyimage()

    @mock.patch.object(fu, 'get_fs_type')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(hu, 'is_block_device')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage_target_not_block_device(self, mock_lbd, mock_u_ras,
                                                  mock_u_e, mock_au_c,
                                                  mock_au_h, mock_au_l,
                                                  mock_au_g, mock_fu_ef,
                                                  mock_http_req, mock_yaml,
                                                  mock_get_size, mock_md5,
                                                  mock_ibd, mock_os_path,
                                                  mock_get_fs_type):
        mock_os_path.return_value = True
        mock_ibd.return_value = False
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr._add_configdrive_image()
        msg = 'TARGET processor .* is not a block device'
        with self.assertRaisesRegexp(errors.WrongDeviceError, msg):
            self.mgr.do_copyimage()

    @mock.patch('fuel_agent.manager.Manager.move_files_to_their_places')
    @mock.patch.object(fu, 'get_fs_type')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(hu, 'is_block_device')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage_md5_matches(self, mock_lbd, mock_u_ras, mock_u_e,
                                      mock_au_c, mock_au_h, mock_au_l,
                                      mock_au_g, mock_fu_ef, mock_http_req,
                                      mock_yaml, mock_get_size, mock_md5,
                                      mock_ibd, mock_os_path,
                                      mock_get_fs_type, mock_mfttp):
        mock_os_path.return_value = True
        mock_ibd.return_value = True
        mock_get_size.return_value = 123
        mock_md5.side_effect = ['fakemd5', 'really_fakemd5', 'fakemd5']
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr.driver.image_scheme.images[0].size = 1234
        self.mgr.driver.image_scheme.images[0].md5 = 'really_fakemd5'
        self.mgr._add_configdrive_image()
        self.assertEqual(2, len(self.mgr.driver.image_scheme.images))
        self.mgr.do_copyimage()
        expected_md5_calls = [mock.call('/tmp/config-drive.img', 123),
                              mock.call('/dev/mapper/os-root', 1234),
                              mock.call('/dev/sda7', 123)]
        self.assertEqual(expected_md5_calls, mock_md5.call_args_list)
        self.assertTrue(mock_mfttp.called)

    @mock.patch.object(fu, 'get_fs_type')
    @mock.patch.object(hu, 'is_block_device')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(utils, 'calculate_md5')
    @mock.patch('os.path.getsize')
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(fu, 'extend_fs')
    @mock.patch.object(au, 'GunzipStream')
    @mock.patch.object(au, 'LocalFile')
    @mock.patch.object(au, 'HttpUrl')
    @mock.patch.object(au, 'Chain')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(utils, 'render_and_save')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_copyimage_md5_mismatch(self, mock_lbd, mock_u_ras, mock_u_e,
                                       mock_au_c, mock_au_h, mock_au_l,
                                       mock_au_g, mock_fu_ef, mock_http_req,
                                       mock_yaml, mock_get_size, mock_md5,
                                       mock_os_path, mock_ibd,
                                       mock_get_fs_type):
        mock_os_path.return_value = True
        mock_ibd.return_value = True
        mock_get_size.return_value = 123
        mock_md5.side_effect = ['fakemd5', 'really_fakemd5', 'fakemd5']
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_SAMPLE
        mock_au_c.return_value = FakeChain()
        self.mgr.driver.image_scheme.images[0].size = 1234
        self.mgr.driver.image_scheme.images[0].md5 = 'fakemd5'
        self.mgr._add_configdrive_image()
        self.assertEqual(2, len(self.mgr.driver.image_scheme.images))
        self.assertRaises(errors.ImageChecksumMismatchError,
                          self.mgr.do_copyimage)

    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.os', create=True)
    def test_mount_target_mtab_is_link(self, mock_os, mock_open, mock_utils,
                                       mock_fu):
        mock_os.path.islink.return_value = True
        mock_utils.execute.return_value = (None, None)
        self.mgr.driver._partition_scheme = objects.PartitionScheme()
        self.mgr.mount_target('fake_chroot')
        mock_open.assert_called_once_with('fake_chroot/etc/mtab', 'wt',
                                          encoding='utf-8')
        mock_os.path.islink.assert_called_once_with('fake_chroot/etc/mtab')
        mock_os.remove.assert_called_once_with('fake_chroot/etc/mtab')

    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.os', create=True)
    def test_mount_target(self, mock_os, mock_open, mock_utils, mock_fu):
        mock_os.path.islink.return_value = False
        self.mgr.driver._partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var/lib', fs_type='xfs')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/boot', fs_type='ext2')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='swap', fs_type='swap')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var', fs_type='ext4')
        fake_mtab = """
proc /proc proc rw,noexec,nosuid,nodev 0 0
sysfs /sys sysfs rw,noexec,nosuid,nodev 0 0
none /sys/kernel/debug debugfs rw 0 0
none /sys/kernel/security securityfs rw 0 0
udev /dev devtmpfs rw,mode=0755 0 0
devpts /dev/pts devpts rw,noexec,nosuid,gid=5,mode=0620 0 0
tmpfs /run tmpfs rw,noexec,nosuid,size=10%,mode=0755 0 0
none /run/lock tmpfs rw,noexec,nosuid,nodev,size=5242880 0 0
none /run/shm tmpfs rw,nosuid,nodev 0 0"""
        mock_utils.execute.return_value = (fake_mtab, None)
        self.mgr.mount_target('fake_chroot')
        self.assertEqual([mock.call('fake_chroot/'),
                          mock.call('fake_chroot/boot'),
                          mock.call('fake_chroot/var'),
                          mock.call('fake_chroot/var/lib'),
                          mock.call('fake_chroot/sys'),
                          mock.call('fake_chroot/dev'),
                          mock.call('fake_chroot/proc')],
                         mock_utils.makedirs_if_not_exists.call_args_list)
        self.assertEqual([mock.call('ext4', 'fake', 'fake_chroot/'),
                          mock.call('ext2', 'fake', 'fake_chroot/boot'),
                          mock.call('ext4', 'fake', 'fake_chroot/var'),
                          mock.call('xfs', 'fake', 'fake_chroot/var/lib')],
                         mock_fu.mount_fs.call_args_list)
        self.assertEqual([mock.call('fake_chroot', '/sys'),
                          mock.call('fake_chroot', '/dev'),
                          mock.call('fake_chroot', '/proc')],
                         mock_fu.mount_bind.call_args_list)
        file_handle = mock_open.return_value.__enter__.return_value
        file_handle.write.assert_called_once_with(fake_mtab)
        mock_open.assert_called_once_with('fake_chroot/etc/mtab', 'wt',
                                          encoding='utf-8')
        mock_os.path.islink.assert_called_once_with('fake_chroot/etc/mtab')
        self.assertFalse(mock_os.remove.called)

    @mock.patch('fuel_agent.manager.fu', create=True)
    def test_umount_target(self, mock_fu):
        self.mgr.driver._partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var/lib', fs_type='xfs')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/boot', fs_type='ext2')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='swap', fs_type='swap')
        self.mgr.driver.partition_scheme.add_fs(
            device='fake', mount='/var', fs_type='ext4')
        self.mgr.umount_target('fake_chroot')
        self.assertEqual([mock.call('fake_chroot/proc'),
                          mock.call('fake_chroot/dev'),
                          mock.call('fake_chroot/sys'),
                          mock.call('fake_chroot/var/lib'),
                          mock.call('fake_chroot/boot'),
                          mock.call('fake_chroot/var'),
                          mock.call('fake_chroot/')],
                         mock_fu.umount_fs.call_args_list)

    @mock.patch('fuel_agent.utils.fs.mount_fs_temp')
    def test_mount_target_flat(self, mock_mfst):
        def mfst_side_effect(*args, **kwargs):
            if '/dev/fake1' in args:
                return '/tmp/dir1'
            elif '/dev/fake2' in args:
                return '/tmp/dir2'
        mock_mfst.side_effect = mfst_side_effect
        self.mgr.driver._partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device='/dev/fake1', mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device='/dev/fake2', mount='/var/lib/', fs_type='ext4')
        self.assertEqual({'/': '/tmp/dir1', '/var/lib': '/tmp/dir2'},
                         self.mgr.mount_target_flat())
        self.assertEqual([mock.call('ext4', '/dev/fake1'),
                          mock.call('ext4', '/dev/fake2')],
                         mock_mfst.call_args_list)

    @mock.patch('fuel_agent.manager.shutil.rmtree')
    @mock.patch('fuel_agent.utils.fs.umount_fs')
    def test_umount_target_flat(self, mock_umfs, mock_rmtree):
        mount_map = {'/': '/tmp/dir1', '/var/lib': '/tmp/dir2'}
        self.mgr.umount_target_flat(mount_map)
        mock_umfs.assert_has_calls(
            [mock.call('/tmp/dir1'), mock.call('/tmp/dir2')],
            any_order=True)

    @mock.patch('fuel_agent.manager.shutil.rmtree')
    @mock.patch('fuel_agent.manager.os.path.exists')
    @mock.patch('fuel_agent.manager.utils.execute')
    @mock.patch('fuel_agent.manager.Manager.umount_target_flat')
    @mock.patch('fuel_agent.manager.Manager.mount_target_flat')
    def test_move_files_to_their_places(self, mock_mtf, mock_utf,
                                        mock_ute, mock_ope, mock_shrmt):

        def ope_side_effect(path):
            if path == '/tmp/dir1/var/lib':
                return True

        mock_ope.side_effect = ope_side_effect
        mock_mtf.return_value = {'/': '/tmp/dir1', '/var/lib': '/tmp/dir2'}
        self.mgr.move_files_to_their_places()
        self.assertEqual(
            [mock.call('rsync', '-avH', '/tmp/dir1/var/lib/', '/tmp/dir2')],
            mock_ute.call_args_list)
        self.assertEqual(
            [mock.call('/tmp/dir1/var/lib')],
            mock_shrmt.call_args_list)

    @mock.patch('fuel_agent.manager.shutil.rmtree')
    @mock.patch('fuel_agent.manager.os.path.exists')
    @mock.patch('fuel_agent.manager.utils.execute')
    @mock.patch('fuel_agent.manager.Manager.umount_target_flat')
    @mock.patch('fuel_agent.manager.Manager.mount_target_flat')
    def test_move_files_to_their_places_not_remove(self, mock_mtf, mock_utf,
                                                   mock_ute, mock_ope,
                                                   mock_shrmt):

        def ope_side_effect(path):
            if path == '/tmp/dir1/var/lib':
                return True

        mock_ope.side_effect = ope_side_effect
        mock_mtf.return_value = {'/': '/tmp/dir1', '/var/lib': '/tmp/dir2'}
        self.mgr.move_files_to_their_places(remove_src=False)
        self.assertEqual(
            [mock.call('rsync', '-avH', '/tmp/dir1/var/lib/', '/tmp/dir2')],
            mock_ute.call_args_list)
        self.assertFalse(mock_shrmt.called)


class TestImageBuild(unittest2.TestCase):
    @mock.patch('yaml.load')
    @mock.patch.object(utils, 'init_http_request')
    @mock.patch.object(utils, 'get_driver')
    def setUp(self, mock_driver, mock_http, mock_yaml):
        super(self.__class__, self).setUp()
        mock_driver.return_value = nailgun.NailgunBuildImage

        # TEST_ROOT_PASSWORD = crypt.crypt('qwerty')
        self.TEST_ROOT_PASSWORD = ('$6$KyOsgFgf9cLbGNST$Ej0Usihfy7W/WT2H0z0mC'
                                   '1DapC/IUpA0jF.Fs83mFIdkGYHL9IOYykRCjfssH.'
                                   'YL4lHbmrvOd/6TIfiyh1hDY1')

        image_conf = {
            "image_data": {
                "/": {
                    "container": "gzip",
                    "format": "ext4",
                    "uri": "http:///centos_65_x86_64.img.gz",
                },
            },
            "output": "/var/www/nailgun/targetimages",
            "repos": [
                {
                    "name": "repo",
                    "uri": "http://some",
                    'type': 'deb',
                    'suite': '/',
                    'section': '',
                    'priority': 1001
                }
            ],
            "codename": "trusty",
            "hashed_root_password": self.TEST_ROOT_PASSWORD,
        }
        self.mgr = manager.Manager(image_conf)

    @mock.patch.object(manager.Manager, '_set_apt_repos')
    @mock.patch('fuel_agent.manager.bu', create=True)
    @mock.patch('fuel_agent.manager.fu', create=True)
    @mock.patch('fuel_agent.manager.utils', create=True)
    @mock.patch('fuel_agent.manager.os', create=True)
    @mock.patch('fuel_agent.manager.shutil.move')
    @mock.patch('fuel_agent.manager.open',
                create=True, new_callable=mock.mock_open)
    @mock.patch('fuel_agent.manager.yaml.safe_dump')
    @mock.patch.object(manager.Manager, 'mount_target')
    @mock.patch.object(manager.Manager, 'umount_target')
    def test_do_build_image(self, mock_umount_target, mock_mount_target,
                            mock_yaml_dump, mock_open, mock_shutil_move,
                            mock_os, mock_utils,
                            mock_fu, mock_bu, mock_set_apt_repos):

        loops = [objects.Loop(), objects.Loop()]

        self.mgr.driver._image_scheme = objects.ImageScheme([
            objects.Image('file:///fake/img.img.gz', loops[0], 'ext4', 'gzip'),
            objects.Image('file:///fake/img-boot.img.gz',
                          loops[1], 'ext2', 'gzip')])
        self.mgr.driver._partition_scheme = objects.PartitionScheme()
        self.mgr.driver.partition_scheme.add_fs(
            device=loops[0], mount='/', fs_type='ext4')
        self.mgr.driver.partition_scheme.add_fs(
            device=loops[1], mount='/boot', fs_type='ext2')
        self.mgr.driver.metadata_uri = 'file:///fake/img.yaml'
        self.mgr.driver._operating_system = objects.Ubuntu(
            repos=[
                objects.DEBRepo('ubuntu', 'http://fakeubuntu',
                                'trusty', 'fakesection', priority=900),
                objects.DEBRepo('ubuntu_zero', 'http://fakeubuntu_zero',
                                'trusty', 'fakesection', priority=None),
                objects.DEBRepo('mos', 'http://fakemos',
                                'mosX.Y', 'fakesection', priority=1000)],
            packages=['fakepackage1', 'fakepackage2'],
            user_accounts=[
                objects.User(name='root', password=None, homedir='/root',
                             hashed_password=self.TEST_ROOT_PASSWORD)])
        self.mgr.driver.operating_system.proxies = objects.RepoProxies(
            proxies={'fake': 'fake'},
            direct_repo_addr_list='fake_addr')
        self.mgr.driver.operating_system.minor = 4
        self.mgr.driver.operating_system.major = 14
        mock_os.path.exists.return_value = False
        mock_os.path.join.return_value = '/tmp/imgdir/proc'
        mock_os.path.basename.side_effect = ['img.img.gz', 'img-boot.img.gz']
        mock_bu.create_sparse_tmp_file.side_effect = \
            ['/tmp/img', '/tmp/img-boot']
        mock_bu.attach_file_to_free_loop_device.side_effect = [
            '/dev/loop0', '/dev/loop1']
        mock_bu.mkdtemp_smart.return_value = '/tmp/imgdir'
        getsize_side = [20, 2, 10, 1]
        mock_os.path.getsize.side_effect = getsize_side
        md5_side = ['fakemd5_raw', 'fakemd5_gzip',
                    'fakemd5_raw_boot', 'fakemd5_gzip_boot']
        mock_utils.calculate_md5.side_effect = md5_side
        mock_bu.containerize.side_effect = ['/tmp/img.gz', '/tmp/img-boot.gz']
        mock_bu.stop_chrooted_processes.side_effect = [
            False, True, False, True]
        metadata = {'os': {'name': 'Ubuntu', 'major': 14, 'minor': 4},
                    'packages': self.mgr.driver.operating_system.packages}

        self.mgr.do_build_image()

        self.assertEqual(
            [mock.call('/fake/img.img.gz'),
             mock.call('/fake/img-boot.img.gz')],
            mock_os.path.exists.call_args_list)
        self.assertEqual([mock.call(dir=CONF.image_build_dir,
                                    suffix=CONF.image_build_suffix,
                                    size=CONF.sparse_file_size)] * 2,
                         mock_bu.create_sparse_tmp_file.call_args_list)
        self.assertEqual(
            [mock.call(
                '/tmp/img',
                loop_device_major_number=CONF.loop_device_major_number,
                max_loop_devices_count=CONF.max_loop_devices_count,
                max_attempts=CONF.max_allowed_attempts_attach_image),
             mock.call(
                '/tmp/img-boot',
                loop_device_major_number=CONF.loop_device_major_number,
                max_loop_devices_count=CONF.max_loop_devices_count,
                max_attempts=CONF.max_allowed_attempts_attach_image)
             ],
            mock_bu.attach_file_to_free_loop_device.call_args_list)
        self.assertEqual([mock.call(fs_type='ext4', fs_options='',
                                    fs_label='', dev='/dev/loop0'),
                          mock.call(fs_type='ext2', fs_options='',
                                    fs_label='', dev='/dev/loop1')],
                         mock_fu.make_fs.call_args_list)
        mock_bu.mkdtemp_smart.assert_called_once_with(
            CONF.image_build_dir, CONF.image_build_suffix)
        mock_mount_target.assert_called_once_with(
            '/tmp/imgdir', treat_mtab=False, pseudo=False)
        self.assertEqual([mock.call('/tmp/imgdir')] * 2,
                         mock_bu.suppress_services_start.call_args_list)
        mock_bu.run_debootstrap.assert_called_once_with(
            uri='http://fakeubuntu', suite='trusty', chroot='/tmp/imgdir',
            attempts=CONF.fetch_packages_attempts,
            proxies={'fake': 'fake'}, direct_repo_addr='fake_addr')
        mock_bu.set_apt_get_env.assert_called_once_with()
        mock_bu.pre_apt_get.assert_called_once_with(
            '/tmp/imgdir', allow_unsigned_file=CONF.allow_unsigned_file,
            force_ipv4_file=CONF.force_ipv4_file, proxies={'fake': 'fake'},
            direct_repo_addr='fake_addr')
        driver_os = self.mgr.driver.operating_system
        mock_set_apt_repos.assert_called_with(
            '/tmp/imgdir',
            driver_os.repos,
            proxies=driver_os.proxies.proxies,
            direct_repo_addrs=driver_os.proxies.direct_repo_addr_list
        )

        mock_utils.makedirs_if_not_exists.assert_called_once_with(
            '/tmp/imgdir/proc')
        self.assertEqual([
            mock.call('tune2fs', '-O', '^has_journal', '/dev/loop0'),
            mock.call('tune2fs', '-O', 'has_journal', '/dev/loop0')],
            mock_utils.execute.call_args_list)
        mock_fu.mount_bind.assert_called_once_with('/tmp/imgdir', '/proc')
        mock_bu.populate_basic_dev.assert_called_once_with('/tmp/imgdir')
        mock_bu.run_apt_get.assert_called_once_with(
            '/tmp/imgdir', packages=['fakepackage1', 'fakepackage2'],
            attempts=CONF.fetch_packages_attempts)
        mock_bu.do_post_inst.assert_called_once_with(
            '/tmp/imgdir',
            hashed_root_password=self.TEST_ROOT_PASSWORD,
            allow_unsigned_file=CONF.allow_unsigned_file,
            force_ipv4_file=CONF.force_ipv4_file)

        signal_calls = mock_bu.stop_chrooted_processes.call_args_list
        self.assertEqual(2 * [mock.call('/tmp/imgdir', signal=signal.SIGTERM),
                              mock.call('/tmp/imgdir', signal=signal.SIGKILL)],
                         signal_calls)
        self.assertEqual(
            [mock.call('/tmp/imgdir/proc')] * 2,
            mock_fu.umount_fs.call_args_list)
        self.assertEqual(
            [mock.call(
                '/tmp/imgdir', pseudo=False)] * 2,
            mock_umount_target.call_args_list)
        self.assertEqual(
            [mock.call('/dev/loop0'), mock.call('/dev/loop1')] * 2,
            mock_bu.deattach_loop.call_args_list)
        self.assertEqual([mock.call('/tmp/img'), mock.call('/tmp/img-boot')],
                         mock_bu.shrink_sparse_file.call_args_list)
        self.assertEqual([mock.call('/tmp/img'),
                          mock.call('/fake/img.img.gz'),
                          mock.call('/tmp/img-boot'),
                          mock.call('/fake/img-boot.img.gz')],
                         mock_os.path.getsize.call_args_list)
        self.assertEqual([mock.call('/tmp/img', 20),
                          mock.call('/fake/img.img.gz', 2),
                          mock.call('/tmp/img-boot', 10),
                          mock.call('/fake/img-boot.img.gz', 1)],
                         mock_utils.calculate_md5.call_args_list)
        self.assertEqual([mock.call('/tmp/img', 'gzip',
                                    chunk_size=CONF.data_chunk_size),
                          mock.call('/tmp/img-boot', 'gzip',
                                    chunk_size=CONF.data_chunk_size)],
                         mock_bu.containerize.call_args_list)
        mock_open.assert_called_once_with('/fake/img.yaml', 'wt',
                                          encoding='utf-8')
        self.assertEqual(
            [mock.call('/tmp/img.gz', '/fake/img.img.gz'),
             mock.call('/tmp/img-boot.gz', '/fake/img-boot.img.gz')],
            mock_shutil_move.call_args_list)

        for repo in self.mgr.driver.operating_system.repos:
            metadata.setdefault('repos', []).append({
                'type': 'deb',
                'name': repo.name,
                'uri': repo.uri,
                'suite': repo.suite,
                'section': repo.section,
                'priority': repo.priority,
                'meta': repo.meta})
        metadata['images'] = [
            {
                'raw_md5': md5_side[0],
                'raw_size': getsize_side[0],
                'raw_name': None,
                'container_name':
                os.path.basename(
                    self.mgr.driver.image_scheme.images[0].uri.split(
                        'file://', 1)[1]),
                'container_md5': md5_side[1],
                'container_size': getsize_side[1],
                'container': self.mgr.driver.image_scheme.images[0].container,
                'format': self.mgr.driver.image_scheme.images[0].format
            },
            {
                'raw_md5': md5_side[2],
                'raw_size': getsize_side[2],
                'raw_name': None,
                'container_name':
                os.path.basename(
                    self.mgr.driver.image_scheme.images[1].uri.split(
                        'file://', 1)[1]),
                'container_md5': md5_side[3],
                'container_size': getsize_side[3],
                'container': self.mgr.driver.image_scheme.images[1].container,
                'format': self.mgr.driver.image_scheme.images[1].format
            }
        ]
        mock_yaml_dump.assert_called_once_with(metadata, stream=mock_open())


class TestManagerMultipathPartition(unittest2.TestCase):

    @mock.patch('fuel_agent.drivers.nailgun.Nailgun.parse_image_meta',
                return_value={})
    @mock.patch.object(hu, 'list_block_devices')
    def setUp(self, mock_lbd, mock_image_meta):
        super(TestManagerMultipathPartition, self).setUp()
        mock_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_MPATH
        data = copy.deepcopy(test_nailgun.PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] =\
            test_nailgun.MPATH_DISK_KS_SPACES
        self.mgr = manager.Manager(data)

    @mock.patch.object(mu, 'mdclean_all')
    @mock.patch.object(manager.utils, 'refresh_multipath')
    @mock.patch.object(hu, 'is_multipath_device')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(manager.utils, 'blacklist_udev_rules')
    @mock.patch.object(manager.utils, 'unblacklist_udev_rules')
    @mock.patch.object(manager.utils, 'execute')
    @mock.patch.object(fu, 'make_fs')
    @mock.patch.object(hu, 'list_block_devices')
    def test_do_partitioning_mp(self, mock_hu_lbd, mock_fu_mf, mock_exec,
                                mock_unbl, mock_bl, mock_os_path, mock_mp,
                                mock_refresh_multipath, mock_mdclean_all):
        mock_os_path.return_value = True
        mock_hu_lbd.return_value = test_nailgun.LIST_BLOCK_DEVICES_MPATH
        self.mgr._make_partitions = mock.MagicMock()
        mock_mp.side_effect = [True, False]
        seq = mock.Mock()
        seq.attach_mock(mock_bl, 'blacklist')
        seq.attach_mock(mock_unbl, 'unblacklist')
        seq.attach_mock(self.mgr._make_partitions, '_make_partitions')
        seq.attach_mock(mock_refresh_multipath, 'refresh_multipath')

        self.mgr.do_partitioning()

        seq_calls = [
            mock.call.blacklist(udev_rules_dir='/etc/udev/rules.d',
                                udev_rules_lib_dir='/lib/udev/rules.d',
                                udev_empty_rule='empty_rule',
                                udev_rename_substr='.renamedrule'),
            mock.call._make_partitions([mock.ANY]),
            mock.call.unblacklist(udev_rules_dir='/etc/udev/rules.d',
                                  udev_rename_substr='.renamedrule'),
            mock.call._make_partitions([mock.ANY]),
            mock.call.refresh_multipath()]
        self.assertEqual(seq_calls, seq.mock_calls)

        parted_list = seq.mock_calls[1][1][0]
        self.assertEqual(parted_list[0].name, '/dev/sdc')
        parted_list = seq.mock_calls[3][1][0]
        self.assertEqual(parted_list[0].name, '/dev/mapper/12312')

        mock_fu_mf_expected_calls = [
            mock.call('ext2', '', '', '/dev/mapper/12312-part3'),
            mock.call('ext4', '', '', '/dev/sdc3')]
        self.assertEqual(mock_fu_mf_expected_calls, mock_fu_mf.call_args_list)

    @mock.patch.object(manager.utils, 'udevadm_trigger_blocks')
    @mock.patch.object(manager.os.path, 'exists')
    @mock.patch.object(fu, 'make_fs')
    @mock.patch.object(pu, 'set_gpt_type')
    @mock.patch.object(pu, 'set_partition_flag')
    @mock.patch.object(pu, 'make_partition')
    @mock.patch.object(pu, 'make_label')
    @mock.patch.object(manager.utils, 'wait_for_udev_settle')
    def test_paritition_settle(self, mock_utils_wait, mock_make_label,
                               mock_make_partition, mock_set_partition_flag,
                               mock_set_gpt_type, mock_make_fs,
                               mock_exists, mock_utils_trigger
                               ):
        self.mgr._make_partitions(self.mgr.driver.partition_scheme.parteds)

        for call in mock_utils_wait.mock_calls:
            self.assertEqual(call, mock.call(attempts=10))

        self.assertEqual(len(mock_utils_trigger.call_args_list), 8)

        self.assertEqual(mock_make_label.mock_calls, [
            mock.call('/dev/mapper/12312', 'gpt'),
            mock.call('/dev/sdc', 'gpt')])

        self.assertEqual(mock_make_partition.mock_calls, [
            mock.call('/dev/mapper/12312', 1, 25, 'primary',
                      alignment='optimal'),
            mock.call('/dev/mapper/12312', 26, 226, 'primary',
                      alignment='optimal'),
            mock.call('/dev/mapper/12312', 227, 427, 'primary',
                      alignment='optimal'),
            mock.call('/dev/mapper/12312', 428, 628, 'primary',
                      alignment='optimal'),
            mock.call('/dev/mapper/12312', 629, 649, 'primary',
                      alignment='optimal'),
            mock.call('/dev/sdc', 1, 25, 'primary', alignment='optimal'),
            mock.call('/dev/sdc', 26, 226, 'primary', alignment='optimal'),
            mock.call('/dev/sdc', 227, 427, 'primary', alignment='optimal')])

        self.assertEqual(mock_set_partition_flag.mock_calls, [
            mock.call('/dev/mapper/12312', 1, 'bios_grub'),
            mock.call('/dev/sdc', 1, 'bios_grub')])

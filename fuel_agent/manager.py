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

import os
import shutil
import signal
import tempfile
import yaml

from oslo.config import cfg
import six

from fuel_agent import errors
from fuel_agent.openstack.common import log as logging
from fuel_agent.utils import artifact as au
from fuel_agent.utils import build as bu
from fuel_agent.utils import fs as fu
from fuel_agent.utils import grub as gu
from fuel_agent.utils import lvm as lu
from fuel_agent.utils import md as mu
from fuel_agent.utils import partition as pu
from fuel_agent.utils import provision
from fuel_agent.utils import utils

opts = [
    cfg.StrOpt(
        'nc_template_path',
        default='/usr/share/fuel-agent/cloud-init-templates',
        help='Path to directory with cloud init templates',
    ),
    cfg.StrOpt(
        'tmp_path',
        default='/tmp',
        help='Temporary directory for file manipulations',
    ),
    cfg.StrOpt(
        'config_drive_path',
        default='/tmp/config-drive.img',
        help='Path where to store generated config drive image',
    ),
    cfg.StrOpt(
        'udev_rules_dir',
        default='/etc/udev/rules.d',
        help='Path where to store actual rules for udev daemon',
    ),
    cfg.StrOpt(
        'udev_rules_lib_dir',
        default='/lib/udev/rules.d',
        help='Path where to store default rules for udev daemon',
    ),
    cfg.StrOpt(
        'udev_rename_substr',
        default='.renamedrule',
        help='Substring to which file extension .rules be renamed',
    ),
    cfg.StrOpt(
        'udev_empty_rule',
        default='empty_rule',
        help='Correct empty rule for udev daemon',
    ),
    cfg.StrOpt(
        'image_build_suffix',
        default='.fuel-agent-image',
        help='Suffix which is used while creating temporary files',
    ),
    cfg.IntOpt(
        'grub_timeout',
        default=5,
        help='Timeout in secs for GRUB'
    ),
    cfg.IntOpt(
        'max_loop_devices_count',
        default=255,
        # NOTE(agordeev): up to 256 loop devices could be allocated up to
        # kernel version 2.6.23, and the limit (from version 2.6.24 onwards)
        # isn't theoretically present anymore.
        help='Maximum allowed loop devices count to use'
    ),
    cfg.IntOpt(
        'sparse_file_size',
        # XXX: Apparently Fuel configures the node root filesystem to span
        # the whole hard drive. However 2 GB filesystem created with default
        # options can grow at most to 2 TB (1024x its initial size). This
        # maximal size can be configured by mke2fs -E resize=NNN option,
        # however the version of e2fsprogs shipped with CentOS 6.[65] seems
        # to silently ignore the `resize' option. Therefore make the initial
        # filesystem a bit bigger so it can grow to 8 TB.
        default=8192,
        help='Size of sparse file in MiBs'
    ),
    cfg.IntOpt(
        'loop_device_major_number',
        default=7,
        help='System-wide major number for loop device'
    ),
    cfg.IntOpt(
        'fetch_packages_attempts',
        default=10,
        help='Maximum allowed debootstrap/apt-get attempts to execute'
    ),
    cfg.StrOpt(
        'allow_unsigned_file',
        default='allow_unsigned_packages',
        help='File where to store apt setting for unsigned packages'
    ),
    cfg.StrOpt(
        'force_ipv4_file',
        default='force_ipv4',
        help='File where to store apt setting for forcing IPv4 usage'
    ),
]

cli_opts = [
    cfg.StrOpt(
        'data_driver',
        default='nailgun',
        help='Data driver'
    ),
    cfg.StrOpt(
        'image_build_dir',
        default='/tmp',
        help='Directory where the image is supposed to be built',
    ),
]

CONF = cfg.CONF
CONF.register_opts(opts)
CONF.register_cli_opts(cli_opts)

LOG = logging.getLogger(__name__)


class Manager(object):
    def __init__(self, data):
        self.driver = utils.get_driver(CONF.data_driver)(data)

    def do_clean_filesystems(self):
        # NOTE(agordeev): it turns out that only mkfs.xfs needs '-f' flag in
        # order to force recreation of filesystem.
        # This option will be added to mkfs.xfs call explicitly in fs utils.
        # TODO(asvechnikov): need to refactor processing keep_flag logic when
        # data model will become flat
        for fs in self.driver.partition_scheme.fss:
            found_images = [img for img in self.driver.image_scheme.images
                            if img.target_device == fs.device]

            if not fs.keep_data and not found_images:
                fu.make_fs(fs.type, fs.options, fs.label, fs.device)

    def do_partitioning(self):
        LOG.debug('--- Partitioning disks (do_partitioning) ---')

        if self.driver.partition_scheme.skip_partitioning:
            LOG.debug('Some of fs has keep_data flag, '
                      'partitioning is skiping')
            self.do_clean_filesystems()
            return

        # If disks are not wiped out at all, it is likely they contain lvm
        # and md metadata which will prevent re-creating a partition table
        # with 'device is busy' error.
        mu.mdclean_all()
        lu.lvremove_all()
        lu.vgremove_all()
        lu.pvremove_all()

        LOG.debug("Enabling udev's rules blacklisting")
        utils.blacklist_udev_rules(udev_rules_dir=CONF.udev_rules_dir,
                                   udev_rules_lib_dir=CONF.udev_rules_lib_dir,
                                   udev_rename_substr=CONF.udev_rename_substr,
                                   udev_empty_rule=CONF.udev_empty_rule)

        for parted in self.driver.partition_scheme.parteds:
            for prt in parted.partitions:
                # We wipe out the beginning of every new partition
                # right after creating it. It allows us to avoid possible
                # interactive dialog if some data (metadata or file system)
                # present on this new partition and it also allows udev not
                # hanging trying to parse this data.
                utils.execute('dd', 'if=/dev/zero', 'bs=1M',
                              'seek=%s' % max(prt.begin - 3, 0), 'count=5',
                              'of=%s' % prt.device, check_exit_code=[0])
                # Also wipe out the ending of every new partition.
                # Different versions of md stores metadata in different places.
                # Adding exit code 1 to be accepted as for handling situation
                # when 'no space left on device' occurs.
                utils.execute('dd', 'if=/dev/zero', 'bs=1M',
                              'seek=%s' % max(prt.end - 3, 0), 'count=5',
                              'of=%s' % prt.device, check_exit_code=[0, 1])

        for parted in self.driver.partition_scheme.parteds:
            pu.make_label(parted.name, parted.label)
            for prt in parted.partitions:
                pu.make_partition(prt.device, prt.begin, prt.end, prt.type)
                for flag in prt.flags:
                    pu.set_partition_flag(prt.device, prt.count, flag)
                if prt.guid:
                    pu.set_gpt_type(prt.device, prt.count, prt.guid)
                # If any partition to be created doesn't exist it's an error.
                # Probably it's again 'device or resource busy' issue.
                if not os.path.exists(prt.name):
                    raise errors.PartitionNotFoundError(
                        'Partition %s not found after creation' % prt.name)

        LOG.debug("Disabling udev's rules blacklisting")
        utils.unblacklist_udev_rules(
            udev_rules_dir=CONF.udev_rules_dir,
            udev_rename_substr=CONF.udev_rename_substr)

        # If one creates partitions with the same boundaries as last time,
        # there might be md and lvm metadata on those partitions. To prevent
        # failing of creating md and lvm devices we need to make sure
        # unused metadata are wiped out.
        mu.mdclean_all()
        lu.lvremove_all()
        lu.vgremove_all()
        lu.pvremove_all()

        # creating meta disks
        for md in self.driver.partition_scheme.mds:
            mu.mdcreate(md.name, md.level, md.devices, md.metadata)

        # creating physical volumes
        for pv in self.driver.partition_scheme.pvs:
            lu.pvcreate(pv.name, metadatasize=pv.metadatasize,
                        metadatacopies=pv.metadatacopies)

        # creating volume groups
        for vg in self.driver.partition_scheme.vgs:
            lu.vgcreate(vg.name, *vg.pvnames)

        # creating logical volumes
        for lv in self.driver.partition_scheme.lvs:
            lu.lvcreate(lv.vgname, lv.name, lv.size)

        # making file systems
        for fs in self.driver.partition_scheme.fss:
            found_images = [img for img in self.driver.image_scheme.images
                            if img.target_device == fs.device]
            if not found_images:
                fu.make_fs(fs.type, fs.options, fs.label, fs.device)

    def _make_configdrive_image(self, src_files):
        bs = 4096
        configdrive_device = self.driver.partition_scheme.configdrive_device()
        size = utils.execute('blockdev', '--getsize64', configdrive_device)[0]
        size = int(size.strip())

        utils.execute('truncate', '--size=%d' % size, CONF.config_drive_path)
        fu.make_fs(
            fs_type='ext2',
            fs_options=' -b %d -F ' % bs,
            fs_label='-L config-2',
            dev=six.text_type(CONF.config_drive_path))

        mount_point = tempfile.mkdtemp(dir=CONF.tmp_path)
        try:
            fu.mount_fs('ext2', CONF.config_drive_path, mount_point)
            for file_path in src_files:
                name = os.path.basename(file_path)
                if os.path.isdir(file_path):
                    shutil.copytree(file_path, os.path.join(mount_point, name))
                else:
                    shutil.copy2(file_path, mount_point)
        except Exception as exc:
            LOG.error('Error copying files to configdrive: %s', exc)
            raise
        finally:
            fu.umount_fs(mount_point)
            os.rmdir(mount_point)

    def _prepare_configdrive_files(self):
        # see data sources part of cloud-init documentation
        # for directory structure
        cd_root = tempfile.mkdtemp(dir=CONF.tmp_path)
        cd_latest = os.path.join(cd_root, 'openstack', 'latest')
        md_output_path = os.path.join(cd_latest, 'meta_data.json')
        ud_output_path = os.path.join(cd_latest, 'user_data')
        os.makedirs(cd_latest)

        cc_output_path = os.path.join(CONF.tmp_path, 'cloud_config.txt')
        bh_output_path = os.path.join(CONF.tmp_path, 'boothook.txt')

        tmpl_dir = CONF.nc_template_path
        utils.render_and_save(
            tmpl_dir,
            self.driver.configdrive_scheme.template_names('cloud_config'),
            self.driver.configdrive_scheme.template_data(),
            cc_output_path
        )
        utils.render_and_save(
            tmpl_dir,
            self.driver.configdrive_scheme.template_names('boothook'),
            self.driver.configdrive_scheme.template_data(),
            bh_output_path
        )
        utils.render_and_save(
            tmpl_dir,
            self.driver.configdrive_scheme.template_names('meta-data_json'),
            self.driver.configdrive_scheme.template_data(),
            md_output_path
        )

        utils.execute(
            'write-mime-multipart', '--output=%s' % ud_output_path,
            '%s:text/cloud-boothook' % bh_output_path,
            '%s:text/cloud-config' % cc_output_path)
        return [os.path.join(cd_root, 'openstack')]

    def do_configdrive(self):
        LOG.debug('--- Creating configdrive (do_configdrive) ---')
        files = self._prepare_configdrive_files()
        self._make_configdrive_image(files)
        self._add_configdrive_image()

    def _add_configdrive_image(self):
        configdrive_device = self.driver.partition_scheme.configdrive_device()
        if configdrive_device is None:
            raise errors.WrongPartitionSchemeError(
                'Error while trying to get configdrive device: '
                'configdrive device not found')
        size = os.path.getsize(CONF.config_drive_path)
        md5 = utils.calculate_md5(CONF.config_drive_path, size)

        fs_type = fu.get_fs_type(CONF.config_drive_path)

        self.driver.image_scheme.add_image(
            uri='file://%s' % CONF.config_drive_path,
            target_device=configdrive_device,
            format=fs_type,
            container='raw',
            size=size,
            md5=md5,
        )

    def do_copyimage(self):
        LOG.debug('--- Copying images (do_copyimage) ---')
        for image in self.driver.image_scheme.images:
            LOG.debug('Processing image: %s' % image.uri)
            processing = au.Chain()

            LOG.debug('Appending uri processor: %s' % image.uri)
            processing.append(image.uri)

            if image.uri.startswith('http://'):
                LOG.debug('Appending HTTP processor')
                processing.append(au.HttpUrl)
            elif image.uri.startswith('file://'):
                LOG.debug('Appending FILE processor')
                processing.append(au.LocalFile)

            if image.container == 'gzip':
                LOG.debug('Appending GZIP processor')
                processing.append(au.GunzipStream)

            LOG.debug('Appending TARGET processor: %s' % image.target_device)
            processing.append(image.target_device)

            LOG.debug('Launching image processing chain')
            processing.process()

            if image.size and image.md5:
                LOG.debug('Trying to compare image checksum')
                actual_md5 = utils.calculate_md5(image.target_device,
                                                 image.size)
                if actual_md5 == image.md5:
                    LOG.debug('Checksum matches successfully: md5=%s' %
                              actual_md5)
                else:
                    raise errors.ImageChecksumMismatchError(
                        'Actual checksum %s mismatches with expected %s for '
                        'file %s' % (actual_md5, image.md5,
                                     image.target_device))
            else:
                LOG.debug('Skipping image checksum comparing. '
                          'Ether size or hash have been missed')

            LOG.debug('Extending image file systems')
            if image.format in ('ext2', 'ext3', 'ext4', 'xfs'):
                LOG.debug('Extending %s %s' %
                          (image.format, image.target_device))
                fu.extend_fs(image.format, image.target_device)
        self.move_files_to_their_places()

    def move_files_to_their_places(self, remove_src=True):
        """Move files from mount points to where those files should be.

        :param remove_src: Remove source files after sync if True (default).
        """

        # NOTE(kozhukalov): The thing is that sometimes we
        # have file system images and mount point hierachies
        # which are not aligned. Let's say, we have root file system
        # image, while partition scheme says that two file systems should
        # be created on the node: / and /var.
        # In this case root image has /var directory with a set of files.
        # Obviously, we need to move all these files from /var directory
        # on the root file system to /var file system because /var
        # directory will be used as mount point.
        # In order to achieve this we mount all existent file
        # systems into a flat set of temporary directories. We then
        # try to find specific paths which correspond to mount points
        # and move all files from these paths to corresponding file systems.

        mount_map = self.mount_target_flat()
        for fs_mount in sorted(mount_map):
            head, tail = os.path.split(fs_mount)
            LOG.debug('Trying to move files for %s file system', fs_mount)
            while head != fs_mount:
                LOG.debug('Checking whether %s is a separate mount point or '
                          'not', head)
                if head in mount_map:
                    LOG.debug('File system %s is mounted into %s',
                              head, mount_map[head])
                    check_path = os.path.join(mount_map[head], tail)
                    LOG.debug('Trying to check if path %s exists', check_path)
                    if os.path.exists(check_path):
                        LOG.debug('Path exists. Trying to sync all files '
                                  'from %s to %s', check_path,
                                  mount_map[fs_mount])
                        src_path = check_path + "/"
                        utils.execute('rsync', '-avH', src_path,
                                      mount_map[fs_mount])
                        if remove_src:
                            shutil.rmtree(check_path)
                        break
                if head == '/':
                    break
                head, _tail = os.path.split(head)
                tail = os.path.join(_tail, tail)
        self.umount_target_flat(mount_map)

    def mount_target_flat(self):
        """Mount a set of file systems into a set of temporary directories

        :returns: Mount map dict
        """

        LOG.debug('Mounting target file systems into a flat set '
                  'of temporary directories')
        mount_map = {}
        for fs in self.driver.partition_scheme.fss:
            if fs.mount == 'swap':
                continue
            # It is an ugly hack to resolve python2/3 encoding issues and
            # should be removed after transistion to python3
            try:
                type(fs.mount) is unicode
                fs_mount = fs.mount.encode('ascii', 'ignore')
            except NameError:
                fs_mount = fs.mount
            fs_mount = os.path.normpath(fs_mount)
            mount_map[fs_mount] = fu.mount_fs_temp(fs.type, str(fs.device))
        LOG.debug('Flat mount map: %s', mount_map)
        return mount_map

    def umount_target_flat(self, mount_map):
        """Umount file systems previously mounted into temporary directories.

        :param mount_map: Mount map dict
        """

        for mount_point in six.itervalues(mount_map):
            fu.umount_fs(mount_point)
            shutil.rmtree(mount_point)

    def mount_target(self, chroot, treat_mtab=True, pseudo=True):
        """Mount a set of file systems into a chroot

        :param chroot: Directory where to mount file systems
        :param treat_mtab: If mtab needs to be actualized (Default: True)
        :param pseudo: If pseudo file systems
        need to be mounted (Default: True)
        """
        LOG.debug('Mounting target file systems: %s', chroot)
        # Here we are going to mount all file systems in partition scheme.
        for fs in self.driver.partition_scheme.fs_sorted_by_depth():
            if fs.mount == 'swap':
                continue
            mount = chroot + fs.mount
            utils.makedirs_if_not_exists(mount)
            fu.mount_fs(fs.type, str(fs.device), mount)

        if pseudo:
            for path in ('/sys', '/dev', '/proc'):
                utils.makedirs_if_not_exists(chroot + path)
                fu.mount_bind(chroot, path)

        if treat_mtab:
            mtab = utils.execute(
                'chroot', chroot, 'grep', '-v', 'rootfs', '/proc/mounts')[0]
            mtab_path = chroot + '/etc/mtab'
            if os.path.islink(mtab_path):
                os.remove(mtab_path)
            with open(mtab_path, 'wb') as f:
                f.write(mtab)

    def umount_target(self, chroot, pseudo=True):
        LOG.debug('Umounting target file systems: %s', chroot)
        if pseudo:
            for path in ('/proc', '/dev', '/sys'):
                fu.umount_fs(chroot + path)
        for fs in self.driver.partition_scheme.fs_sorted_by_depth(
                reverse=True):
            if fs.mount == 'swap':
                continue
            fu.umount_fs(chroot + fs.mount)

    def do_bootloader(self):
        LOG.debug('--- Installing bootloader (do_bootloader) ---')
        chroot = '/tmp/target'
        self.mount_target(chroot)

        mount2uuid = {}
        for fs in self.driver.partition_scheme.fss:
            mount2uuid[fs.mount] = utils.execute(
                'blkid', '-o', 'value', '-s', 'UUID', fs.device,
                check_exit_code=[0])[0].strip()

        if '/' not in mount2uuid:
            raise errors.WrongPartitionSchemeError(
                'Error: device with / mountpoint has not been found')

        grub = self.driver.grub

        guessed_version = gu.guess_grub_version(chroot=chroot)
        if guessed_version != grub.version:
            grub.version = guessed_version
            LOG.warning('Grub version differs from which the operating system '
                        'should have by default. Found version in image: '
                        '{0}'.format(guessed_version))
        boot_device = self.driver.partition_scheme.boot_device(grub.version)
        install_devices = [d.name for d in self.driver.partition_scheme.parteds
                           if d.install_bootloader]

        grub.append_kernel_params('root=UUID=%s ' % mount2uuid['/'])

        kernel = grub.kernel_name or \
            gu.guess_kernel(chroot=chroot, regexp=grub.kernel_regexp)
        initrd = grub.initrd_name or \
            gu.guess_initrd(chroot=chroot, regexp=grub.initrd_regexp)

        if grub.version == 1:
            gu.grub1_cfg(kernel=kernel, initrd=initrd,
                         kernel_params=grub.kernel_params, chroot=chroot,
                         grub_timeout=CONF.grub_timeout)
            gu.grub1_install(install_devices, boot_device, chroot=chroot)
        else:
            # TODO(kozhukalov): implement which kernel to use by default
            # Currently only grub1_cfg accepts kernel and initrd parameters.
            gu.grub2_cfg(kernel_params=grub.kernel_params, chroot=chroot,
                         grub_timeout=CONF.grub_timeout)
            gu.grub2_install(install_devices, chroot=chroot)

        provision.udev_nic_naming_rules(
            chroot, self.driver.configdrive_scheme.common.udevrules)

        # NOTE(agordeev): NEED_PERSISTENT_NET allows the including of
        # 70-persistent-net.rules udev rule into the initramfs.
        # Actual only for Trusty. udev hook from Xenial will include
        # custom udev rules automatically.
        update_initramfs_conf = 'etc/initramfs-tools/update-initramfs.conf'
        utils.execute(
            'sed', '-i', '-e', '$aexport\ NEED_PERSISTENT_NET=yes',
            os.path.join(chroot, update_initramfs_conf))
        utils.execute('chroot', chroot, 'dpkg-divert', '--local', '--add',
                      os.path.join(os.path.sep, update_initramfs_conf))

        # FIXME(agordeev): Normally, that should be handled out side of
        # fuel-agent. Just a temporary fix to avoid dealing with cloud-init
        # boothooks.
        provision.configure_admin_nic(
            chroot=chroot,
            iface=self.driver.configdrive_scheme.common.admin_iface_name,
            ip=self.driver.configdrive_scheme.common.admin_ip,
            netmask=self.driver.configdrive_scheme.common.admin_mask,
            gw=self.driver.configdrive_scheme.common.gw)

        # FIXME(kozhukalov): Prevent nailgun-agent from doing anything.
        # This ugly hack is to be used together with the command removing
        # this lock file not earlier than /etc/rc.local
        # The reason for this hack to appear is to prevent nailgun-agent from
        # changing mcollective config at the same time when cloud-init
        # does the same. Otherwise, we can end up with corrupted mcollective
        # config. For details see https://bugs.launchpad.net/fuel/+bug/1449186
        LOG.debug('Preventing nailgun-agent from doing '
                  'anything until it is unlocked')
        utils.makedirs_if_not_exists(os.path.join(chroot, 'etc/nailgun-agent'))
        with open(os.path.join(chroot, 'etc/nailgun-agent/nodiscover'), 'w'):
            pass

        with open(chroot + '/etc/fstab', 'wb') as f:
            for fs in self.driver.partition_scheme.fss:
                # TODO(kozhukalov): Think of improving the logic so as to
                # insert a meaningful fsck order value which is last zero
                # at fstab line. Currently we set it into 0 which means
                # a corresponding file system will never be checked. We assume
                # puppet or other configuration tool will care of it.
                if fs.mount == '/':
                    f.write('UUID=%s %s %s defaults,errors=panic 0 0\n' %
                            (mount2uuid[fs.mount], fs.mount, fs.type))
                else:
                    f.write('UUID=%s %s %s defaults 0 0\n' %
                            (mount2uuid[fs.mount], fs.mount, fs.type))

        # NOTE(agordeev): rebuild initramfs image for including
        # custom udev rules from /etc/udev/rules.d/
        bu.recompress_initramfs(chroot)

        self.umount_target(chroot)

    def do_reboot(self):
        LOG.debug('--- Rebooting node (do_reboot) ---')
        utils.execute('reboot')

    def do_provisioning(self):
        LOG.debug('--- Provisioning (do_provisioning) ---')
        self.do_partitioning()
        self.do_configdrive()
        self.do_copyimage()
        self.do_bootloader()
        LOG.debug('--- Provisioning END (do_provisioning) ---')

    # TODO(kozhukalov): Split this huge method
    # into a set of smaller ones
    # https://bugs.launchpad.net/fuel/+bug/1444090
    def do_build_image(self):
        """Building OS images

        Includes the following steps
        1) create temporary sparse files for all images (truncate)
        2) attach temporary files to loop devices (losetup)
        3) create file systems on these loop devices
        4) create temporary chroot directory
        5) mount loop devices into chroot directory
        6) install operating system (debootstrap and apt-get)
        7) configure OS (clean sources.list and preferences, etc.)
        8) umount loop devices
        9) resize file systems on loop devices
        10) shrink temporary sparse files (images)
        11) containerize (gzip) temporary sparse files
        12) move temporary gzipped files to their final location
        """
        LOG.info('--- Building image (do_build_image) ---')
        # TODO(kozhukalov): Implement metadata
        # as a pluggable data driver to avoid any fixed format.
        metadata = {}

        metadata['os'] = self.driver.operating_system.to_dict()

        # TODO(kozhukalov): implement this using image metadata
        # we need to compare list of packages and repos
        LOG.info('*** Checking if image exists ***')
        if all([os.path.exists(img.uri.split('file://', 1)[1])
                for img in self.driver.image_scheme.images]):
            LOG.debug('All necessary images are available. '
                      'Nothing needs to be done.')
            return
        LOG.debug('At least one of the necessary images is unavailable. '
                  'Starting build process.')
        try:
            LOG.debug('Creating temporary chroot directory')
            utils.makedirs_if_not_exists(CONF.image_build_dir)
            chroot = tempfile.mkdtemp(
                dir=CONF.image_build_dir, suffix=CONF.image_build_suffix)
            LOG.debug('Temporary chroot: %s', chroot)

            proc_path = os.path.join(chroot, 'proc')

            LOG.info('*** Preparing image space ***')
            for image in self.driver.image_scheme.images:
                LOG.debug('Creating temporary sparsed file for the '
                          'image: %s', image.uri)
                img_tmp_file = bu.create_sparse_tmp_file(
                    dir=CONF.image_build_dir, suffix=CONF.image_build_suffix,
                    size=CONF.sparse_file_size)
                LOG.debug('Temporary file: %s', img_tmp_file)

                # we need to remember those files
                # to be able to shrink them and move in the end
                image.img_tmp_file = img_tmp_file

                LOG.debug('Looking for a free loop device')
                image.target_device.name = bu.get_free_loop_device(
                    loop_device_major_number=CONF.loop_device_major_number,
                    max_loop_devices_count=CONF.max_loop_devices_count)

                LOG.debug('Attaching temporary image file to free loop device')
                bu.attach_file_to_loop(img_tmp_file, str(image.target_device))

                # find fs with the same loop device object
                # as image.target_device
                fs = self.driver.partition_scheme.fs_by_device(
                    image.target_device)

                LOG.debug('Creating file system on the image')
                fu.make_fs(
                    fs_type=fs.type,
                    fs_options=fs.options,
                    fs_label=fs.label,
                    dev=str(fs.device))
                if fs.type == 'ext4':
                    LOG.debug('Trying to disable journaling for ext4 '
                              'in order to speed up the build')
                    utils.execute('tune2fs', '-O', '^has_journal',
                                  str(fs.device))

            # mounting all images into chroot tree
            self.mount_target(chroot, treat_mtab=False, pseudo=False)

            LOG.info('*** Shipping image content ***')
            LOG.debug('Installing operating system into image')
            # FIXME(kozhukalov): !!! we need this part to be OS agnostic

            # DEBOOTSTRAP
            # we use first repo as the main mirror
            uri = self.driver.operating_system.repos[0].uri
            suite = self.driver.operating_system.repos[0].suite

            LOG.debug('Preventing services from being get started')
            bu.suppress_services_start(chroot)
            LOG.debug('Installing base operating system using debootstrap')
            bu.run_debootstrap(uri=uri, suite=suite, chroot=chroot,
                               attempts=CONF.fetch_packages_attempts)

            # APT-GET
            LOG.debug('Configuring apt inside chroot')
            LOG.debug('Setting environment variables')
            bu.set_apt_get_env()
            LOG.debug('Allowing unauthenticated repos')
            bu.pre_apt_get(chroot,
                           allow_unsigned_file=CONF.allow_unsigned_file,
                           force_ipv4_file=CONF.force_ipv4_file)

            for repo in self.driver.operating_system.repos:
                LOG.debug('Adding repository source: name={name}, uri={uri},'
                          'suite={suite}, section={section}'.format(
                              name=repo.name, uri=repo.uri,
                              suite=repo.suite, section=repo.section))
                bu.add_apt_source(
                    name=repo.name,
                    uri=repo.uri,
                    suite=repo.suite,
                    section=repo.section,
                    chroot=chroot)
                LOG.debug('Adding repository preference: '
                          'name={name}, priority={priority}'.format(
                              name=repo.name, priority=repo.priority))
                if repo.priority is not None:
                    bu.add_apt_preference(
                        name=repo.name,
                        priority=repo.priority,
                        suite=repo.suite,
                        section=repo.section,
                        chroot=chroot,
                        uri=repo.uri)

                metadata.setdefault('repos', []).append({
                    'type': 'deb',
                    'name': repo.name,
                    'uri': repo.uri,
                    'suite': repo.suite,
                    'section': repo.section,
                    'priority': repo.priority,
                    'meta': repo.meta})

            LOG.debug('Preventing services from being get started')
            bu.suppress_services_start(chroot)

            packages = self.driver.operating_system.packages
            metadata['packages'] = packages

            # we need /proc to be mounted for apt-get success
            utils.makedirs_if_not_exists(proc_path)
            fu.mount_bind(chroot, '/proc')

            bu.populate_basic_dev(chroot)

            LOG.debug('Installing packages using apt-get: %s',
                      ' '.join(packages))
            bu.run_apt_get(chroot, packages=packages,
                           attempts=CONF.fetch_packages_attempts)

            LOG.debug('Post-install OS configuration')
            bu.do_post_inst(chroot,
                            allow_unsigned_file=CONF.allow_unsigned_file,
                            force_ipv4_file=CONF.force_ipv4_file)

            LOG.debug('Making sure there are no running processes '
                      'inside chroot before trying to umount chroot')
            if not bu.stop_chrooted_processes(chroot, signal=signal.SIGTERM):
                if not bu.stop_chrooted_processes(
                        chroot, signal=signal.SIGKILL):
                    raise errors.UnexpectedProcessError(
                        'Stopping chrooted processes failed. '
                        'There are some processes running in chroot %s',
                        chroot)

            LOG.info('*** Finalizing image space ***')
            fu.umount_fs(proc_path)
            # umounting all loop devices
            self.umount_target(chroot, pseudo=False)

            for image in self.driver.image_scheme.images:
                # find fs with the same loop device object
                # as image.target_device
                fs = self.driver.partition_scheme.fs_by_device(
                    image.target_device)

                if fs.type == 'ext4':
                    LOG.debug('Trying to re-enable journaling for ext4')
                    utils.execute('tune2fs', '-O', 'has_journal',
                                  str(fs.device))

                LOG.debug('Deattaching loop device from file: %s',
                          image.img_tmp_file)
                bu.deattach_loop(str(image.target_device))
                LOG.debug('Shrinking temporary image file: %s',
                          image.img_tmp_file)
                bu.shrink_sparse_file(image.img_tmp_file)

                raw_size = os.path.getsize(image.img_tmp_file)
                raw_md5 = utils.calculate_md5(image.img_tmp_file, raw_size)

                LOG.debug('Containerizing temporary image file: %s',
                          image.img_tmp_file)
                img_tmp_containerized = bu.containerize(
                    image.img_tmp_file, image.container,
                    chunk_size=CONF.data_chunk_size)
                img_containerized = image.uri.split('file://', 1)[1]

                # NOTE(kozhukalov): implement abstract publisher
                LOG.debug('Moving image file to the final location: %s',
                          img_containerized)
                shutil.move(img_tmp_containerized, img_containerized)

                container_size = os.path.getsize(img_containerized)
                container_md5 = utils.calculate_md5(
                    img_containerized, container_size)
                metadata.setdefault('images', []).append({
                    'raw_md5': raw_md5,
                    'raw_size': raw_size,
                    'raw_name': None,
                    'container_name': os.path.basename(img_containerized),
                    'container_md5': container_md5,
                    'container_size': container_size,
                    'container': image.container,
                    'format': image.format})

            # NOTE(kozhukalov): implement abstract publisher
            LOG.debug('Image metadata: %s', metadata)
            with open(self.driver.metadata_uri.split('file://', 1)[1],
                      'w') as f:
                yaml.safe_dump(metadata, stream=f)
            LOG.info('--- Building image END (do_build_image) ---')
        except Exception as exc:
            LOG.error('Failed to build image: %s', exc)
            raise
        finally:
            LOG.debug('Finally: stopping processes inside chroot: %s', chroot)

            if not bu.stop_chrooted_processes(chroot, signal=signal.SIGTERM):
                bu.stop_chrooted_processes(chroot, signal=signal.SIGKILL)
            LOG.debug('Finally: umounting procfs %s', proc_path)
            fu.umount_fs(proc_path)
            LOG.debug('Finally: umounting chroot tree %s', chroot)
            self.umount_target(chroot, pseudo=False)
            for image in self.driver.image_scheme.images:
                LOG.debug('Finally: detaching loop device: %s',
                          str(image.target_device))
                try:
                    bu.deattach_loop(str(image.target_device))
                except errors.ProcessExecutionError as e:
                    LOG.warning('Error occured while trying to detach '
                                'loop device %s. Error message: %s',
                                str(image.target_device), e)

                LOG.debug('Finally: removing temporary file: %s',
                          image.img_tmp_file)
                try:
                    os.unlink(image.img_tmp_file)
                except OSError:
                    LOG.debug('Finally: file %s seems does not exist '
                              'or can not be removed', image.img_tmp_file)
            LOG.debug('Finally: removing chroot directory: %s', chroot)
            try:
                os.rmdir(chroot)
            except OSError:
                LOG.debug('Finally: directory %s seems does not exist '
                          'or can not be removed', chroot)

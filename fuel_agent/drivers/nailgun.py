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

import itertools
import math
import os

from oslo_config import cfg
from oslo_log import log as logging
import six
from six.moves.urllib.parse import urljoin
from six.moves.urllib.parse import urlparse
from six.moves.urllib.parse import urlsplit
import yaml

from fuel_agent.drivers import base
from fuel_agent.drivers import ks_spaces_validator
from fuel_agent import errors
from fuel_agent import objects
from fuel_agent.utils import hardware as hu
from fuel_agent.utils import utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('prepare_configdrive', 'fuel_agent.manager')
CONF.import_opt('config_drive_path', 'fuel_agent.manager')
CONF.import_opt('default_root_password', 'fuel_agent.manager')


def match_device(hu_disk, ks_disk):
    """Check if hu_disk and ks_disk are the same device

    Tries to figure out if hu_disk got from hu.list_block_devices
    and ks_spaces_disk given correspond to the same disk device. This
    is the simplified version of hu.match_device

    :param hu_disk: A dict representing disk device how
    it is given by list_block_devices method.
    :param ks_disk: A dict representing disk device according to
     ks_spaces format.

    :returns: True if hu_disk matches ks_spaces_disk else False.
    """
    uspec = hu_disk['uspec']

    # True if at least one by-id link matches ks_disk
    if ('DEVLINKS' in uspec and len(ks_disk.get('extra', [])) > 0
            and any(x.startswith('/dev/disk/by-id') for x in
                    set(uspec['DEVLINKS']) &
                    set(['/dev/%s' % l for l in ks_disk['extra']]))):
        return True

    # True if one of DEVLINKS matches ks_disk id
    if (len(ks_disk.get('extra', [])) == 0
            and 'DEVLINKS' in uspec and 'id' in ks_disk
            and '/dev/%s' % ks_disk['id'] in uspec['DEVLINKS']):
        return True

    return False


class Nailgun(base.BaseDataDriver):
    """Driver for parsing regular volumes metadata from Nailgun."""

    def __init__(self, data):
        super(Nailgun, self).__init__(data)

        # this var states whether boot partition
        # was already allocated on first matching volume
        # or not
        self._boot_partition_done = False
        # this var is used as a flag that /boot fs
        # has already been added. we need this to
        # get rid of md over all disks for /boot partition.
        self._boot_done = False
        self._image_meta = self.parse_image_meta()

        self._operating_system = self.parse_operating_system()
        self._grub = self.parse_grub()
        # parsing partition scheme needs grub and operating system have
        # been parsed
        self._partition_scheme = self.parse_partition_scheme()
        self._configdrive_scheme = self.parse_configdrive_scheme()
        # parsing image scheme needs partition scheme has been parsed
        self._image_scheme = self.parse_image_scheme()

    @property
    def partition_scheme(self):
        return self._partition_scheme

    @property
    def image_scheme(self):
        return self._image_scheme

    @property
    def grub(self):
        return self._grub

    @property
    def have_grub1_by_default(self):
        return (isinstance(self.operating_system, objects.Centos) and
                self.operating_system.major == 6)

    @property
    def operating_system(self):
        return self._operating_system

    @property
    def configdrive_scheme(self):
        return self._configdrive_scheme

    def partition_data(self):
        return self.data['ks_meta']['pm_data']['ks_spaces']

    def _needs_configdrive(self):
        return (CONF.prepare_configdrive or
                os.path.isfile(CONF.config_drive_path))

    @property
    def ks_disks(self):
        return filter(
            lambda x: x['type'] == 'disk' and x['size'] > 0,
            self.partition_data())

    @property
    def boot_disks(self):
        """Property to get suitable list of disks to place '/boot'

        :returns: list of disk where boot partition can be placed
        """
        # FIXME(agordeev): NVMe drives should be skipped as
        # accessing such drives during the boot typically
        # requires using UEFI which is still not supported
        # by fuel-agent (it always installs BIOS variant of
        # grub)
        # * grub bug (http://savannah.gnu.org/bugs/?41883)
        disks = self.ks_disks
        suitable_disks = [
            disk for disk in disks
            if ('nvme' not in disk['name'] and self._is_boot_disk(disk))
        ]
        # NOTE(agordeev) sometimes, there's no separate /boot fs image.
        # Therefore bootloader should be installed into
        # the disk where rootfs image lands. Ironic's case.
        if not suitable_disks and not self._have_boot_partition(disks):
            return [d for d in disks
                    if self._is_root_disk(d) and 'nvme' not in d['name']]
        # FIXME(agordeev): if we have rootfs on fake raid, then /boot should
        # land on it too. We can't proceed with grub-install otherwise.
        md_boot_disks = [
            disk for disk in self.md_os_disks if disk in suitable_disks]
        if md_boot_disks:
            disks = md_boot_disks
        else:
            disks = suitable_disks
        bootable_disk = [disk for disk in disks
                         if disk.get('bootable')]
        if bootable_disk:
            if len(bootable_disk) >= 2:
                raise errors.WrongPartitionSchemeError(
                    "More than one bootable disk found! %{0}".
                    format(bootable_disk))
            return bootable_disk

        return disks

    def _have_boot_partition(self, disks):
        return any(self._is_boot_disk(d) for d in disks)

    def _is_boot_disk(self, disk):
        return any(v["type"] in ('partition', 'raid') and
                   v.get("mount") == "/boot"
                   for v in disk["volumes"])

    def _is_root_disk(self, disk):
        return any(v["type"] in ('partition', 'raid') and
                   v.get("mount") == "/"
                   for v in disk["volumes"])

    def _is_os_volume(self, vol):
        return vol['size'] > 0 and vol['type'] == 'pv' and vol['vg'] == 'os'

    def _is_os_disk(self, disk):
        return any(self._is_os_volume(vol) for vol in disk['volumes'])

    @property
    def md_os_disks(self):
        return [d for d in self.ks_disks
                if d['name'].startswith('md') and self._is_os_disk(d)]

    @property
    def ks_vgs(self):
        return filter(
            lambda x: x['type'] == 'vg',
            self.partition_data())

    @property
    def hu_disks(self):
        """Actual disks which are available on this node

        It is a list of dicts which are formatted other way than
        ks_spaces disks. To match both of those formats use
        _match_device method.
        """
        if not getattr(self, '_hu_disks', None):
            self._hu_disks = hu.list_block_devices(disks=True)
        return self._hu_disks

    def _disk_dev(self, ks_disk):
        # first we try to find a device that matches ks_disk
        # comparing by-id and by-path links
        matched = [hu_disk['device'] for hu_disk in self.hu_disks
                   if match_device(hu_disk, ks_disk)]
        # if we can not find a device by its by-id and by-path links
        # we try to find a device by its name
        fallback = [hu_disk['device'] for hu_disk in self.hu_disks
                    if '/dev/%s' % ks_disk['name'] == hu_disk['device']]

        # Due to udevadm bugs it can return the same ids for different disks.
        # For instance for NVMe disks. In this case matched will contains
        # more than 1 disk and we should use info from fallback
        if len(matched) > 1 and len(fallback) == 1:
            found = fallback
        else:
            found = matched or fallback

        if not found or len(found) > 1:
            raise errors.DiskNotFoundError(
                'Disk not found: %s' % ks_disk['name'])
        return found[0]

    def _get_partition_count(self, name):
        count = 0
        for disk in self.ks_disks:
            count += len([v for v in disk["volumes"]
                          if v.get('name') == name and v['size'] > 0])
        return count

    def _num_ceph_journals(self):
        return self._get_partition_count('cephjournal')

    def _num_ceph_osds(self):
        return self._get_partition_count('ceph')

    def get_os_by_image_meta(self, os_release):
        LOG.debug('--- Getting operating system data by image metadata ---')
        if os_release:
            LOG.debug('Looks like {0} is going to be provisioned'.
                      format(os_release))
            try:
                OS = getattr(objects, os_release['name'])
                os = OS(repos=None, packages=None, major=os_release['major'],
                        minor=os_release['minor'])
                return os
            except (AttributeError, KeyError):
                LOG.warning('Cannot guess operating system release '
                            'from image metadata')

    def get_os_by_profile(self, profile):
        LOG.debug('--- Getting operating system data by profile ---')
        if 'centos' in profile:
            os = objects.Centos(repos=None, packages=None, major=6, minor=5)
            if '7' in profile:
                LOG.debug('Looks like CentOS7.0 is going to be provisioned.')
                os = objects.Centos(repos=None, packages=None, major=7,
                                    minor=0)
            else:
                LOG.debug('Looks like CentOS6.5 is going to be provisioned.')
            return os
        elif 'ubuntu' in profile:
            os = objects.Ubuntu(repos=None, packages=None, major=12, minor=4)
            if '1404' in profile:
                LOG.debug('Looks like Ubuntu1404 is going to be provisioned.')
                os = objects.Ubuntu(repos=None, packages=None, major=14,
                                    minor=4)
            else:
                LOG.debug('Looks like Ubuntu1204 is going to be provisioned.')
            return os
        os = objects.OperatingSystem(repos=None, packages=None)
        return os

    def parse_operating_system(self):
        LOG.debug('--- Preparing operating system data ---')
        os_release = self._image_meta.get('os', None)

        os = self.get_os_by_image_meta(os_release) or \
            self.get_os_by_profile(self.data['profile'].lower())

        # FIXME(dnikishov): until fuel-agent-versioning BP
        # will have been implemented, we need to deal with the case when
        # 9.0 fuel-agent will be managing 6.1 to 8.0 environments, whose
        # provisioning serializers on Nailgun side will not have
        # user_accounts in the ks_meta dict
        try:
            user_accounts = self.data['ks_meta']['user_accounts']
        except KeyError:
            LOG.warning(('This environment does not support non-root accounts '
                         'on the target nodes. Non-root user accounts will '
                         'not be created'))
            user_accounts = []

        for account in user_accounts:
            os.add_user_account(**account)

        return os

    def parse_partition_scheme(self):
        LOG.debug('--- Preparing partition scheme ---')
        data = self.partition_data()
        ks_spaces_validator.validate(data)
        partition_scheme = objects.PartitionScheme()

        ceph_osds = self._num_ceph_osds()
        journals_left = ceph_osds
        ceph_journals = self._num_ceph_journals()

        LOG.debug('Looping over all disks in provision data')
        for disk in self.ks_disks:
            # skipping disk if there are no volumes with size >0
            # to be allocated on it which are not boot partitions
            if all((
                v["size"] <= 0
                for v in disk["volumes"]
                if v["type"] not in ("boot", 'lvm_meta_pool')
                    and v.get("mount") != "/boot"
            )):
                continue
            LOG.debug('Processing disk %s' % disk['name'])
            LOG.debug('Adding gpt table on disk %s' % disk['name'])
            parted = partition_scheme.add_parted(
                name=self._disk_dev(disk), label='gpt')

            # we install bootloader only on every suitable disk
            LOG.debug('Adding bootloader stage0 on disk %s' % disk['name'])
            parted.install_bootloader = True

            # legacy boot partition
            LOG.debug('Adding bios_grub partition on disk %s: size=24' %
                      disk['name'])
            parted.add_partition(size=24, flags=['bios_grub'])
            # uefi partition (for future use)
            LOG.debug('Adding UEFI partition on disk %s: size=200' %
                      disk['name'])
            parted.add_partition(size=200)

            LOG.debug('Looping over all volumes on disk %s' % disk['name'])
            for volume in disk['volumes']:
                LOG.debug('Processing volume: '
                          'name=%s type=%s size=%s mount=%s vg=%s' %
                          (volume.get('name'), volume.get('type'),
                           volume.get('size'), volume.get('mount'),
                           volume.get('vg')))
                if volume['size'] <= 0:
                    LOG.debug('Volume size is zero. Skipping.')
                    continue

                if volume.get('name') == 'cephjournal':
                    LOG.debug('Volume seems to be a CEPH journal volume. '
                              'Special procedure is supposed to be applied.')
                    # We need to allocate a journal partition for each ceph OSD
                    # Determine the number of journal partitions we need on
                    # each device
                    ratio = int(math.ceil(float(ceph_osds) / ceph_journals))

                    # No more than 10GB will be allocated to a single journal
                    # partition
                    size = volume["size"] / ratio
                    if size > 10240:
                        size = 10240

                    # This will attempt to evenly spread partitions across
                    # multiple devices e.g. 5 osds with 2 journal devices will
                    # create 3 partitions on the first device and 2 on the
                    # second
                    if ratio < journals_left:
                        end = ratio
                    else:
                        end = journals_left

                    for i in range(0, end):
                        journals_left -= 1
                        if volume['type'] == 'partition':
                            LOG.debug('Adding CEPH journal partition on '
                                      'disk %s: size=%s' %
                                      (disk['name'], size))
                            prt = parted.add_partition(size=size)
                            LOG.debug('Partition name: %s' % prt.name)
                            if 'partition_guid' in volume:
                                LOG.debug('Setting partition GUID: %s' %
                                          volume['partition_guid'])
                                prt.set_guid(volume['partition_guid'])
                    continue

                if volume['type'] in ('partition', 'pv', 'raid'):
                    if volume.get('mount') != '/boot':
                        LOG.debug('Adding partition on disk %s: size=%s' %
                                  (disk['name'], volume['size']))
                        prt = parted.add_partition(
                            size=volume['size'],
                            keep_data=volume.get('keep_data', False))
                        LOG.debug('Partition name: %s' % prt.name)

                    elif volume.get('mount') == '/boot' \
                            and not self._boot_partition_done \
                            and disk in self.boot_disks:
                        LOG.debug('Adding /boot partition on disk %s: '
                                  'size=%s', disk['name'], volume['size'])
                        prt = parted.add_partition(
                            size=volume['size'],
                            keep_data=volume.get('keep_data', False))
                        LOG.debug('Partition name: %s', prt.name)
                        self._boot_partition_done = True
                    else:
                        LOG.debug('No need to create partition on disk %s. '
                                  'Skipping.', disk['name'])
                        continue

                if volume['type'] == 'partition':
                    if 'partition_guid' in volume:
                        LOG.debug('Setting partition GUID: %s' %
                                  volume['partition_guid'])
                        prt.set_guid(volume['partition_guid'])

                    fs = volume.get('file_system')
                    if fs == 'none':
                        fs = None
                    mount = volume.get('mount')
                    if mount == 'none':
                        mount = None

                    if fs is not None or mount is not None:
                        # NOTE(el): Set default file system to xfs for
                        # the purpose of backward compatibility with
                        # previous versions of fuel-agent.
                        if fs is None:
                            fs = 'xfs'
                        LOG.debug('Adding file system on partition: '
                                  'mount=%s type=%s', mount, fs)
                        partition_scheme.add_fs(
                            device=prt.name,
                            mount=mount,
                            fs_type=fs,
                            fs_label=volume.get('disk_label'))
                        if mount == '/boot' and not self._boot_done:
                            self._boot_done = True

                if volume['type'] == 'pv':
                    LOG.debug('Creating pv on partition: pv=%s vg=%s' %
                              (prt.name, volume['vg']))
                    lvm_meta_size = volume.get('lvm_meta_size', 64)
                    # The reason for that is to make sure that
                    # there will be enough space for creating logical volumes.
                    # Default lvm extension size is 4M. Nailgun volume
                    # manager does not care of it and if physical volume size
                    # is 4M * N + 3M and lvm metadata size is 4M * L then only
                    # 4M * (N-L) + 3M of space will be available for
                    # creating logical extensions. So only 4M * (N-L) of space
                    # will be available for logical volumes, while nailgun
                    # volume manager might reguire 4M * (N-L) + 3M
                    # logical volume. Besides, parted aligns partitions
                    # according to its own algorithm and actual partition might
                    # be a bit smaller than integer number of mebibytes.
                    if lvm_meta_size < 10:
                        raise errors.WrongPartitionSchemeError(
                            'Error while creating physical volume: '
                            'lvm metadata size is too small')
                    metadatasize = int(math.floor((lvm_meta_size - 8) / 2))
                    metadatacopies = 2
                    partition_scheme.vg_attach_by_name(
                        pvname=prt.name, vgname=volume['vg'],
                        metadatasize=metadatasize,
                        metadatacopies=metadatacopies)

                if volume['type'] == 'raid':
                    if 'mount' in volume and \
                            volume['mount'] not in ('none', '/boot'):
                        LOG.debug('Attaching partition to RAID '
                                  'by its mount point %s' % volume['mount'])
                        metadata = 'default'
                        if self.have_grub1_by_default:
                            metadata = '0.90'
                        LOG.debug('Going to use MD metadata version {0}. '
                                  'The version was guessed at the data has '
                                  'been given about the operating system.'
                                  .format(metadata))
                        partition_scheme.md_attach_by_mount(
                            device=prt.name, mount=volume['mount'],
                            fs_type=volume.get('file_system', 'xfs'),
                            fs_label=volume.get('disk_label'),
                            metadata=metadata)

                    if 'mount' in volume and volume['mount'] == '/boot' and \
                            not self._boot_done:
                        LOG.debug('Adding file system on partition: '
                                  'mount=%s type=%s' %
                                  (volume['mount'],
                                   volume.get('file_system', 'ext2')))
                        partition_scheme.add_fs(
                            device=prt.name, mount=volume['mount'],
                            fs_type=volume.get('file_system', 'ext2'),
                            fs_label=volume.get('disk_label'))
                        self._boot_done = True

            # this partition will be used to put there configdrive image
            if (partition_scheme.configdrive_device() is None and
                    self._needs_configdrive() and
                    (self._is_root_disk(disk) or self._is_os_disk(disk))):
                LOG.debug('Adding configdrive partition on disk %s: size=20' %
                          disk['name'])
                parted.add_partition(size=20, configdrive=True)

        # checking if /boot is expected to be created
        if self._have_boot_partition(self.ks_disks) and \
                (not self._boot_partition_done or not self._boot_done):
            raise errors.WrongPartitionSchemeError(
                '/boot partition has not been created for some reasons')

        # checking if configdrive partition is created
        if (not partition_scheme.configdrive_device() and
                self._needs_configdrive()):
            raise errors.WrongPartitionSchemeError(
                'configdrive partition has not been created for some reasons')

        LOG.debug('Looping over all volume groups in provision data')
        for vg in self.ks_vgs:
            LOG.debug('Processing vg %s' % vg['id'])
            LOG.debug('Looping over all logical volumes in vg %s' % vg['id'])
            for volume in vg['volumes']:
                LOG.debug('Processing lv %s' % volume['name'])
                if volume['size'] <= 0:
                    LOG.debug('LogicalVolume size is zero. Skipping.')
                    continue

                if volume['type'] == 'lv':
                    LOG.debug('Adding lv to vg %s: name=%s, size=%s' %
                              (vg['id'], volume['name'], volume['size']))
                    lv = partition_scheme.add_lv(name=volume['name'],
                                                 vgname=vg['id'],
                                                 size=volume['size'])

                    if 'mount' in volume and volume['mount'] != 'none':
                        LOG.debug('Adding file system on lv: '
                                  'mount=%s type=%s' %
                                  (volume['mount'],
                                   volume.get('file_system', 'xfs')))
                        partition_scheme.add_fs(
                            device=lv.device_name, mount=volume['mount'],
                            fs_type=volume.get('file_system', 'xfs'),
                            fs_label=volume.get('disk_label'))

        partition_scheme.elevate_keep_data()
        return partition_scheme

    def parse_configdrive_scheme(self):
        LOG.debug('--- Preparing configdrive scheme ---')
        data = self.data
        configdrive_scheme = objects.ConfigDriveScheme(
            user_accounts=self.operating_system.user_accounts
        )

        LOG.debug('Adding common parameters')

        interface_dicts = [
            dict(name=name, **spec)
            for name, spec
            in six.iteritems(data['interfaces'])
        ]

        admin_interface = next(
            x for x in interface_dicts
            if (x['mac_address'] ==
                data['kernel_options']['netcfg/choose_interface'])
        )

        ssh_auth_keys = data['ks_meta']['authorized_keys']
        if data['ks_meta']['auth_key']:
            ssh_auth_keys.append(data['ks_meta']['auth_key'])

        configdrive_scheme.set_common(
            ssh_auth_keys=ssh_auth_keys,
            hostname=data['hostname'],
            fqdn=data['hostname'],
            name_servers=data['name_servers'],
            search_domain=data['name_servers_search'],
            master_ip=data['ks_meta']['master_ip'],
            master_url='http://%s:8000/api' % data['ks_meta']['master_ip'],
            udevrules=data['kernel_options']['udevrules'],
            admin_mac=data['kernel_options']['netcfg/choose_interface'],
            admin_ip=admin_interface['ip_address'],
            admin_mask=admin_interface['netmask'],
            admin_iface_name=admin_interface['name'],
            timezone=data['ks_meta'].get('timezone', 'America/Los_Angeles'),
            gw=data['ks_meta']['gw'],
            ks_repos=data['ks_meta']['repo_setup']['repos']
        )

        LOG.debug('Adding puppet parameters')
        configdrive_scheme.set_puppet(
            master=data['ks_meta']['puppet_master'],
            enable=data['ks_meta']['puppet_enable']
        )

        LOG.debug('Adding mcollective parameters')
        configdrive_scheme.set_mcollective(
            pskey=data['ks_meta']['mco_pskey'],
            vhost=data['ks_meta']['mco_vhost'],
            host=data['ks_meta']['mco_host'],
            user=data['ks_meta']['mco_user'],
            password=data['ks_meta']['mco_password'],
            connector=data['ks_meta']['mco_connector'],
            enable=data['ks_meta']['mco_enable'],
            identity=data['ks_meta']['mco_identity']
        )

        LOG.debug('Setting configdrive profile %s' % data['profile'])
        configdrive_scheme.set_profile(profile=data['profile'])
        configdrive_scheme.set_cloud_init_templates(
            templates=data['ks_meta'].get('cloud_init_templates', {}))
        return configdrive_scheme

    def parse_grub(self):
        LOG.debug('--- Parse grub settings ---')
        grub = objects.Grub()
        LOG.debug('Appending kernel parameters: %s',
                  self.data['ks_meta']['pm_data']['kernel_params'])
        grub.append_kernel_params(
            self.data['ks_meta']['pm_data']['kernel_params'])
        if 'centos' in self.data['profile'].lower() and \
                not self.data['ks_meta'].get('kernel_lt'):
            LOG.debug('Prefered kernel version is 2.6')
            grub.kernel_regexp = r'^vmlinuz-2\.6.*'
            grub.initrd_regexp = r'^initramfs-2\.6.*'
        grub.version = 1 if self.have_grub1_by_default else 2
        LOG.debug('Grub version is {0}'.format(grub.version))
        return grub

    def parse_image_meta(self):
        LOG.debug('--- Preparing image metadata ---')
        data = self.data
        # FIXME(agordeev): this piece of code for fetching additional image
        # meta data should be factored out of this particular nailgun driver
        # into more common and absract data getter which should be able to deal
        # with various data sources (local file, http(s), etc.) and different
        # data formats ('blob', json, yaml, etc.).
        # So, the manager will combine and manipulate all those multiple data
        # getter instances.
        # Also, the initial data source should be set to sort out chicken/egg
        # problem. Command line option may be useful for such a case.
        # BUG: https://bugs.launchpad.net/fuel/+bug/1430418
        root_uri = data['ks_meta']['image_data']['/']['uri']
        filename = os.path.basename(urlparse(root_uri).path).split('.')[0] + \
            '.yaml'
        metadata_url = urljoin(root_uri, filename)
        try:
            image_meta = yaml.load(
                utils.init_http_request(metadata_url).text)
        except Exception as e:
            LOG.exception(e)
            LOG.debug('Failed to fetch/decode image meta data')
            image_meta = {}
        return image_meta

    def parse_image_scheme(self):
        LOG.debug('--- Preparing image scheme ---')
        data = self.data
        image_meta = self._image_meta
        image_scheme = objects.ImageScheme()
        # We assume for every file system user may provide a separate
        # file system image. For example if partitioning scheme has
        # /, /boot, /var/lib file systems then we will try to get images
        # for all those mount points. Images data are to be defined
        # at provision.json -> ['ks_meta']['image_data']
        LOG.debug('Looping over all images in provision data')
        for mount_point, image_data in six.iteritems(
                data['ks_meta']['image_data']):
            LOG.debug('Adding image for fs %s: uri=%s format=%s container=%s' %
                      (mount_point, image_data['uri'],
                       image_data['format'], image_data['container']))
            iname = os.path.basename(urlparse(image_data['uri']).path)
            imeta = next(itertools.chain(
                (img for img in image_meta.get('images', [])
                 if img['container_name'] == iname), [{}]))
            image_scheme.add_image(
                uri=image_data['uri'],
                target_device=self.partition_scheme.fs_by_mount(
                    mount_point).device,
                format=image_data['format'],
                container=image_data['container'],
                size=imeta.get('raw_size'),
                md5=imeta.get('raw_md5'),
            )
        return image_scheme


class Ironic(Nailgun):
    def __init__(self, data):
        super(Ironic, self).__init__(data)

    def parse_configdrive_scheme(self):
        pass


class NailgunBuildImage(base.BaseDataDriver):

    # TODO(kozhukalov):
    # This list of packages is used by default only if another
    # list isn't given in build image data. In the future
    # we need to handle package list in nailgun. Even more,
    # in the future, we'll be building not only ubuntu images
    # and we'll likely move this list into some kind of config.
    DEFAULT_TRUSTY_PACKAGES = [
        "acl",
        "anacron",
        "bash-completion",
        "bridge-utils",
        "bsdmainutils",
        "build-essential",
        "cloud-init",
        "curl",
        "daemonize",
        "debconf-utils",
        "gdisk",
        "grub-pc",
        "hpsa-dkms",
        "i40e-dkms",
        "linux-firmware",
        "linux-firmware-nonfree",
        "linux-headers-generic-lts-trusty",
        "linux-image-generic-lts-trusty",
        "lvm2",
        "mcollective",
        "mdadm",
        "nailgun-agent",
        "nailgun-mcagents",
        "network-checker",
        "ntp",
        "openssh-client",
        "openssh-server",
        "puppet",
        "python-amqp",
        "ruby-augeas",
        "ruby-ipaddress",
        "ruby-json",
        "ruby-netaddr",
        "ruby-openstack",
        "ruby-shadow",
        "ruby-stomp",
        "telnet",
        "ubuntu-minimal",
        "ubuntu-standard",
        "uuid-runtime",
        "vim",
        "virt-what",
        "vlan",
    ]

    def __init__(self, data):
        super(NailgunBuildImage, self).__init__(data)
        self._image_scheme = objects.ImageScheme()
        self._partition_scheme = objects.PartitionScheme()

        self.parse_schemes()
        self._operating_system = self.parse_operating_system()

    @property
    def partition_scheme(self):
        return self._partition_scheme

    @property
    def image_scheme(self):
        return self._image_scheme

    @property
    def grub(self):
        return None

    @property
    def operating_system(self):
        return self._operating_system

    @property
    def configdrive_scheme(self):
        return None

    def parse_operating_system(self):
        packages = self.data.get('packages', self.DEFAULT_TRUSTY_PACKAGES)

        repos = []
        for repo in self.data['repos']:
            repos.append(objects.DEBRepo(
                name=repo['name'],
                uri=repo['uri'],
                suite=repo['suite'],
                section=repo['section'],
                priority=repo['priority']))

        proxies = objects.RepoProxies()

        proxy_dict = self.data.get('proxies', {})
        for protocol, uri in six.iteritems(proxy_dict.get('protocols', {})):
            proxies.add_proxy(protocol, uri)
        proxies.add_direct_repo_addrs(proxy_dict.get(
            'direct_repo_addr_list', []))

        os = objects.Ubuntu(repos=repos, packages=packages, major=14, minor=4,
                            proxies=proxies)

        # add root account
        root_password = self.data.get('root_password')
        hashed_root_password = self.data.get('hashed_root_password')

        # for backward compatibily set default password is no password provided
        if root_password is None and hashed_root_password is None:
            root_password = CONF.default_root_password

        os.add_user_account(
            name='root',
            password=root_password,
            homedir='/root',
            hashed_password=hashed_root_password,
        )
        return os

    def parse_schemes(self):

        for mount, image in six.iteritems(self.data['image_data']):
            filename = os.path.basename(urlsplit(image['uri']).path)
            # Loop does not allocate any loop device
            # during initialization.
            device = objects.Loop()

            self._image_scheme.add_image(
                uri='file://' + os.path.join(self.data['output'], filename),
                format=image['format'],
                container=image['container'],
                target_device=device)

            self._partition_scheme.add_fs(
                device=device,
                mount=mount,
                fs_type=image['format'])

            if mount == '/':
                metadata_filename = filename.split('.', 1)[0] + '.yaml'
                self.metadata_uri = 'file://' + os.path.join(
                    self.data['output'], metadata_filename)

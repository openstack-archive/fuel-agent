# -*- coding: utf-8 -*-

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

from oslo_log import log as logging

from fuel_agent import errors
from fuel_agent.objects.partition import fs as f_fs
from fuel_agent.objects.partition import lv as f_lv
from fuel_agent.objects.partition import md as f_md
from fuel_agent.objects.partition import parted as f_parted
from fuel_agent.objects.partition import pv as f_pv
from fuel_agent.objects.partition import vg as f_vg


LOG = logging.getLogger(__name__)


class PartitionScheme(object):
    def __init__(self):
        self.parteds = []
        self.mds = []
        self.pvs = []
        self.vgs = []
        self.lvs = []
        self.fss = []

    def add_parted(self, **kwargs):
        parted = f_parted.Parted(**kwargs)
        self.parteds.append(parted)
        return parted

    def add_pv(self, **kwargs):
        pv = f_pv.PhysicalVolume(**kwargs)
        self.pvs.append(pv)
        return pv

    def add_vg(self, **kwargs):
        vg = f_vg.VolumeGroup(**kwargs)
        self.vgs.append(vg)
        return vg

    def add_lv(self, **kwargs):
        lv = f_lv.LogicalVolume(**kwargs)
        self.lvs.append(lv)
        return lv

    def add_fs(self, **kwargs):
        fs = f_fs.FileSystem(**kwargs)
        if fs.mount and not os.path.isabs(fs.mount) and fs.mount != 'swap':
            raise errors.WrongFSMount(
                'Incorrect mount point %s' % fs.mount)
        self.fss.append(fs)
        return fs

    def add_md(self, **kwargs):
        mdkwargs = {}
        mdkwargs['name'] = kwargs.get('name') or self.md_next_name()
        mdkwargs['level'] = kwargs.get('level') or 'mirror'
        mdkwargs['metadata'] = kwargs.get('metadata') or 'default'
        md = f_md.MultipleDevice(**mdkwargs)
        self.mds.append(md)
        return md

    def md_by_name(self, name):
        return next((x for x in self.mds if x.name == name), None)

    def md_by_mount(self, mount):
        fs = self.fs_by_mount(mount)
        if fs:
            return self.md_by_name(fs.device)

    def md_attach_by_mount(self, device, mount, spare=False, **kwargs):
        md = self.md_by_mount(mount)
        if not md:
            md = self.add_md(**kwargs)
            fskwargs = {}
            fskwargs['device'] = md.name
            fskwargs['mount'] = mount
            fskwargs['fs_type'] = kwargs.pop('fs_type', None)
            fskwargs['fs_options'] = kwargs.pop('fs_options', None)
            fskwargs['fs_label'] = kwargs.pop('fs_label', None)
            self.add_fs(**fskwargs)
        md.add_spare(device) if spare else md.add_device(device)
        return md

    def md_next_name(self):
        count = 0
        while True:
            name = '/dev/md%s' % count
            if name not in [md.name for md in self.mds]:
                return name
            if count >= 127:
                raise errors.MDAlreadyExistsError(
                    'Error while generating md name: '
                    'names from /dev/md0 to /dev/md127 seem to be busy, '
                    'try to generate md name manually')
            count += 1

    def partition_by_name(self, name):
        return next((parted.partition_by_name(name)
                    for parted in self.parteds
                    if parted.partition_by_name(name)), None)

    def vg_by_name(self, vgname):
        return next((x for x in self.vgs if x.name == vgname), None)

    def pv_by_name(self, pvname):
        return next((x for x in self.pvs if x.name == pvname), None)

    def vg_attach_by_name(self, pvname, vgname,
                          metadatasize=16, metadatacopies=2):
        vg = self.vg_by_name(vgname) or self.add_vg(name=vgname)
        pv = self.pv_by_name(pvname) or self.add_pv(
            name=pvname, metadatasize=metadatasize,
            metadatacopies=metadatacopies)
        vg.add_pv(pv.name)

    def fs_by_mount(self, mount):
        return next((x for x in self.fss if x.mount == mount), None)

    def fs_by_device(self, device):
        return next((x for x in self.fss if x.device == device), None)

    def fs_sorted_by_depth(self, reverse=False):
        """Getting file systems sorted by path length.

        Shorter paths earlier.
        ['/', '/boot', '/var', '/var/lib/mysql']
        :param reverse: Sort backward (Default: False)
        """
        def key(x):
            return x.mount.rstrip(os.path.sep).count(os.path.sep)
        return sorted(self.fss_w_mountpoints, key=key, reverse=reverse)

    @property
    def fss_w_mountpoints(self):
        """Returns a list of file systems which have mountpoints"""
        # NOTE: `swap` mountpoint is not a real mountpoint, so has
        # to be skipped.
        return filter(lambda f: f.mount is not None and f.mount != "swap",
                      self.fss)

    def lv_by_device_name(self, device_name):
        return next((x for x in self.lvs if x.device_name == device_name),
                    None)

    def root_device(self):
        fs = self.fs_by_mount('/')
        if not fs:
            raise errors.WrongPartitionSchemeError(
                'Error while trying to find root device: '
                'root file system not found')
        return fs.device

    def boot_device(self, grub_version=2):
        # We assume /boot is a separate partition. If it is not
        # then we try to use root file system
        boot_fs = self.fs_by_mount('/boot') or self.fs_by_mount('/')
        if not boot_fs:
            raise errors.WrongPartitionSchemeError(
                'Error while trying to find boot device: '
                'boot file system not fount, '
                'it must be a separate mount point')

        if grub_version == 1:
            # Legacy GRUB has a limitation. It is not able to mount MD devices.
            # If it is MD compatible it is only able to ignore MD metadata
            # and to mount one of those devices which are parts of MD device,
            # but it is possible only if MD device is a MIRROR.
            md = self.md_by_name(boot_fs.device)
            if md:
                try:
                    return md.devices[0]
                except IndexError:
                    raise errors.WrongPartitionSchemeError(
                        'Error while trying to find boot device: '
                        'md device %s does not have devices attached' %
                        md.name)
            # Legacy GRUB is not able to mount LVM devices.
            if self.lv_by_device_name(boot_fs.device):
                raise errors.WrongPartitionSchemeError(
                    'Error while trying to find boot device: '
                    'found device is %s but legacy grub is not able to '
                    'mount logical volumes' %
                    boot_fs.device)

        return boot_fs.device

    def configdrive_device(self):
        # Configdrive device must be a small (about 10M) partition
        # on one of node hard drives. This partition is necessary
        # only if one uses cloud-init with configdrive.
        for parted in self.parteds:
            for prt in parted.partitions:
                if prt.configdrive:
                    return prt.name

    def elevate_keep_data(self):
        LOG.debug('Elevate keep_data flag from partitions')

        for vg in self.vgs:
            for pvname in vg.pvnames:
                partition = self.partition_by_name(pvname)
                if partition and partition.keep_data:
                    partition.keep_data = False
                    vg.keep_data = True
                    LOG.debug('Set keep_data to vg=%s' % vg.name)

        for lv in self.lvs:
            vg = self.vg_by_name(lv.vgname)
            if vg.keep_data:
                lv.keep_data = True

        # Need to loop over lv again to remove keep flag from vg
        for lv in self.lvs:
            vg = self.vg_by_name(lv.vgname)
            if vg.keep_data and lv.keep_data:
                vg.keep_data = False

        for fs in self.fss:
            lv = self.lv_by_device_name(fs.device)
            if lv:
                if lv.keep_data:
                    lv.keep_data = False
                    fs.keep_data = True
                    LOG.debug('Set keep_data to fs=%s from lv=%s' %
                              (fs.mount, lv.name))
                continue
            partition = self.partition_by_name(fs.device)
            if partition and partition.keep_data:
                partition.keep_data = False
                fs.keep_data = True
                LOG.debug('Set keep flag to fs=%s from partition=%s' %
                          (fs.mount, partition.name))

    @property
    def skip_partitioning(self):
        if any(fs.keep_data for fs in self.fss):
            return True
        if any(lv.keep_data for lv in self.lvs):
            return True
        if any(vg.keep_data for vg in self.vgs):
            return True
        for parted in self.parteds:
            if any(prt.keep_data for prt in parted.partitions):
                return True

    def to_dict(self):
        return {
            'parteds': [parted.to_dict() for parted in self.parteds],
            'mds': [md.to_dict() for md in self.mds],
            'pvs': [pv.to_dict() for pv in self.pvs],
            'vgs': [vg.to_dict() for vg in self.vgs],
            'lvs': [lv.to_dict() for lv in self.lvs],
            'fss': [fs.to_dict() for fs in self.fss],
        }

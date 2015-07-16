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

from fuel_agent.drivers import nailgun
from fuel_agent import objects


class NailgunSimpleDriver(nailgun.Nailgun):
    """Simple driver that do not make any computations.

    This driver digest information that already has all required
    information how to perform partitioning.
    Service that sends data to fuel_agent is responsible for preparing
    it in correct format.
    """

    @property
    def partition_data(self):
        return self.data.get('partitioning', {})

    @classmethod
    def parse_lv_data(cls, raw_lvs):
        return [objects.LV.from_dict(lv) for lv in raw_lvs]

    @classmethod
    def parse_pv_data(cls, raw_pvs):
        return [objects.PV.from_dict(pv) for pv in raw_pvs]

    @classmethod
    def parse_fs_data(cls, raw_fss):
        return [objects.FS.from_dict(fs) for fs in raw_fss]

    @classmethod
    def parse_vg_data(cls, raw_vgs):
        return [objects.VG.from_dict(vg) for vg in raw_vgs]

    @classmethod
    def parse_md_data(cls, raw_mds):
        return [objects.MD.from_dict(md) for md in raw_mds]

    @classmethod
    def parse_parted_data(cls, raw_parteds):
        return [objects.Parted.from_dict(parted) for parted in raw_parteds]

    def parse_partition_scheme(self):
        partition_scheme = objects.PartitionScheme()

        for obj in ('lv', 'pv', 'fs', 'vg', 'md', 'parted'):
            attr = '{0}s'.format(obj)
            parse_method = getattr(self, 'parse_{0}_data'.format(obj))
            raw = self.partition_data.get(attr, {})
            setattr(partition_scheme, attr, parse_method(raw))

        return partition_scheme

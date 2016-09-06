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

import copy

from fuel_agent.objects import base


class Parted(base.Serializable):

    def __init__(self, name, label, partitions=None, install_bootloader=False):
        self.name = name
        self.label = label
        self.partitions = partitions or []
        self.install_bootloader = install_bootloader

    def add_partition(self, **kwargs):
        # TODO(kozhukalov): validate before appending
        # calculating partition name based on device name and partition count
        kwargs['name'] = self.next_name()
        kwargs['count'] = self.next_count()
        kwargs['device'] = self.name
        # if begin is given use its value else use end of last partition
        kwargs['begin'] = kwargs.get('begin', self.next_begin())
        # if end is given use its value else
        # try to calculate it based on size kwarg or
        # raise KeyError
        # (kwargs.pop['size'] will raise error if size is not set)
        kwargs['end'] = kwargs.get('end') or \
            kwargs['begin'] + kwargs.pop('size')
        # if partition_type is given use its value else
        # try to calculate it automatically
        kwargs['partition_type'] = \
            kwargs.get('partition_type', self.next_type())
        partition = Partition(**kwargs)
        self.partitions.append(partition)
        return partition

    @property
    def logical(self):
        return [x for x in self.partitions if x.type == 'logical']

    @property
    def primary(self):
        return [x for x in self.partitions if x.type == 'primary']

    @property
    def extended(self):
        return next((x for x in self.partitions if x.type == 'extended'), None)

    def next_type(self):
        if self.label == 'gpt':
            return 'primary'
        elif self.label == 'msdos':
            if self.extended:
                return 'logical'
            elif len(self.partitions) < 3 and not self.extended:
                return 'primary'
            elif len(self.partitions) == 3 and not self.extended:
                return 'extended'
            # NOTE(agordeev): how to reach that condition?
            else:
                return 'logical'

    def next_count(self, next_type=None):
        next_type = next_type or self.next_type()
        if next_type == 'logical':
            return len(self.logical) + 5
        return len(self.partitions) + 1

    def next_begin(self):
        if not self.partitions:
            return 1
        if self.partitions[-1] == self.extended:
            # NOTE(agordeev): this 1M room could be enough for minimal
            # partition alignment mode for the most of cases.
            return self.partitions[-1].begin + 1
        return self.partitions[-1].end + 1

    def next_name(self):
        if self.next_type() == 'extended':
            return None

        special_devices = ('cciss', 'nvme', 'loop', 'md')
        if any(n in self.name for n in special_devices):
            separator = 'p'
        elif '/dev/mapper' in self.name:
            separator = '-part'
        else:
            separator = ''
        return '%s%s%s' % (self.name, separator, self.next_count())

    def partition_by_name(self, name):
        return next((x for x in self.partitions if x.name == name), None)

    def to_dict(self):
        partitions = [partition.to_dict() for partition in self.partitions]
        return {
            'name': self.name,
            'label': self.label,
            'partitions': partitions,
            'install_bootloader': self.install_bootloader,
        }

    @classmethod
    def from_dict(cls, data):
        data = copy.deepcopy(data)
        raw_partitions = data.pop('partitions')
        partitions = [Partition.from_dict(partition)
                      for partition in raw_partitions]
        return cls(partitions=partitions, **data)


class Partition(base.Serializable):

    def __init__(self, name, count, device, begin, end, partition_type,
                 flags=None, guid=None, configdrive=False, keep_data=False):
        self.keep_data = keep_data
        self.name = name
        self.count = count
        self.device = device
        self.begin = begin
        self.end = end
        self.type = partition_type
        self.flags = flags or []
        self.guid = guid
        self.configdrive = configdrive

    def set_flag(self, flag):
        if flag not in self.flags:
            self.flags.append(flag)

    def set_guid(self, guid):
        self.guid = guid

    def to_dict(self):
        return {
            'name': self.name,
            'count': self.count,
            'device': self.device,
            'begin': self.begin,
            'end': self.end,
            'partition_type': self.type,
            'flags': self.flags,
            'guid': self.guid,
            'configdrive': self.configdrive,
            'keep_data': self.keep_data,
        }

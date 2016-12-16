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

import mock
import six
import unittest2
import yaml

from fuel_agent.drivers import nailgun
from fuel_agent import errors
from fuel_agent import objects
from fuel_agent.objects import image
from fuel_agent.utils import utils


SWIFT = {
    'disk_label': None,
    'file_system': 'xfs',
    'mount': 'none',
    'name': 'swift-storage',
    'partition_guid': 'deadbeef-9d34-4175-8ded-1ce68967a5ee',
    'size': 10,
    'type': 'partition'
}

CEPH_JOURNAL = {
    "partition_guid": "45b0969e-9b03-4f30-b4c6-b4b80ceff106",
    "name": "cephjournal",
    "mount": "none",
    "disk_label": "",
    "type": "partition",
    "file_system": "none",
    "size": 0
}
CEPH_DATA = {
    "partition_guid": "4fbd7e29-9d25-41b8-afd0-062c0ceff05d",
    "name": "ceph",
    "mount": "none",
    "disk_label": "",
    "type": "partition",
    "file_system": "none",
    "size": 3333
}
PROVISION_SAMPLE_DATA = {
    "profile": "pro_fi-le",
    "name_servers_search": "\"domain.tld\"",
    "uid": "1",
    "interfaces": {
        "eth2": {
            "static": "0",
            "mac_address": "08:00:27:b1:d7:15"
        },
        "eth1": {
            "static": "0",
            "mac_address": "08:00:27:46:43:60"
        },
        "eth0": {
            "ip_address": "10.20.0.3",
            "dns_name": "node-1.domain.tld",
            "netmask": "255.255.255.0",
            "static": "0",
            "mac_address": "08:00:27:79:da:80"
        }
    },
    "interfaces_extra": {
        "eth2": {
            "onboot": "no",
            "peerdns": "no"
        },
        "eth1": {
            "onboot": "no",
            "peerdns": "no"
        },
        "eth0": {
            "onboot": "yes",
            "peerdns": "no"
        }
    },
    "power_type": "ssh",
    "power_user": "root",
    "kernel_options": {
        "udevrules": "08:00:27:79:da:80_eth0,08:00:27:46:43:60_eth1,"
                     "08:00:27:b1:d7:15_eth2",
        "netcfg/choose_interface": "08:00:27:79:da:80"
    },
    "power_address": "10.20.0.253",
    "name_servers": "\"10.20.0.2\"",
    "ks_meta": {
        "gw": "10.20.0.1",
        "image_data": {
            "/": {
                "uri": "http://fake.host.org:123/imgs/fake_image.img.gz",
                "format": "ext4",
                "container": "gzip"
            }
        },
        "timezone": "America/Los_Angeles",
        "master_ip": "10.20.0.2",
        "mco_identity": -1,
        "mco_enable": 1,
        "mco_vhost": "mcollective",
        "mco_pskey": "unset",
        "mco_user": "mcollective",
        "puppet_enable": 0,
        "fuel_version": "5.0.1",
        "install_log_2_syslog": 1,
        "mco_password": "marionette",
        "puppet_auto_setup": 1,
        "puppet_master": "fuel.domain.tld",
        "mco_auto_setup": 1,
        "auth_key": "fake_auth_key",
        "authorized_keys": ["fake_authorized_key1", "fake_authorized_key2"],
        "repo_setup": {
            "repos": [
                {
                    "name": "repo1",
                    "type": "deb",
                    "uri": "uri1",
                    "suite": "suite",
                    "section": "section",
                    "priority": 1001
                },
                {
                    "name": "repo2",
                    "type": "deb",
                    "uri": "uri2",
                    "suite": "suite",
                    "section": "section",
                    "priority": 1001
                }
            ]
        },
        "pm_data": {
            "kernel_params": "console=ttyS0,9600 console=tty0 rootdelay=90 "
                             "nomodeset",
            "ks_spaces": [
                {
                    "name": "sda",
                    "extra": [
                        "disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-"
                        "b385c7cd",
                        "disk/by-id/ata-VBOX_HARDDISK_VB69050467-b385c7cd"
                    ],
                    "free_space": 64907,
                    "volumes": [
                        {
                            "type": "boot",
                            "size": 300
                        },
                        {
                            "mount": "/boot",
                            "size": 200,
                            "type": "raid",
                            "file_system": "ext2",
                            "name": "Boot"
                        },
                        {
                            "mount": "/tmp",
                            "size": 200,
                            "type": "partition",
                            "file_system": "ext2",
                            "partition_guid": "fake_guid",
                            "name": "TMP"
                        },
                        {
                            "type": "lvm_meta_pool",
                            "size": 0
                        },
                        {
                            "size": 19438,
                            "type": "pv",
                            "lvm_meta_size": 64,
                            "vg": "os"
                        },
                        {
                            "size": 45597,
                            "type": "pv",
                            "lvm_meta_size": 64,
                            "vg": "image"
                        }
                    ],
                    "type": "disk",
                    "id": "sda",
                    "size": 65535
                },
                {
                    "name": "sdb",
                    "extra": [
                        "disk/by-id/scsi-SATA_VBOX_HARDDISK_VBf2923215-"
                            "708af674",
                        "disk/by-id/ata-VBOX_HARDDISK_VBf2923215-708af674"
                    ],
                    "free_space": 64907,
                    "volumes": [
                        {
                            "type": "boot",
                            "size": 300
                        },
                        {
                            "mount": "/boot",
                            "size": 200,
                            "type": "raid",
                            "file_system": "ext2",
                            "name": "Boot"
                        },
                        {
                            "type": "lvm_meta_pool",
                            "size": 64
                        },
                        {
                            "size": 0,
                            "type": "pv",
                            "lvm_meta_size": 0,
                            "vg": "os"
                        },
                        {
                            "size": 64971,
                            "type": "pv",
                            "lvm_meta_size": 64,
                            "vg": "image"
                        }
                    ],
                    "type": "disk",
                    "id": "sdb",
                    "size": 65535
                },
                {
                    "name": "sdc",
                    "extra": [
                        "disk/by-id/scsi-SATA_VBOX_HARDDISK_VB50ee61eb-"
                            "84e74fdf",
                        "disk/by-id/ata-VBOX_HARDDISK_VB50ee61eb-84e74fdf"
                    ],
                    "free_space": 64907,
                    "volumes": [
                        {
                            "type": "boot",
                            "size": 300
                        },
                        {
                            "mount": "/boot",
                            "size": 200,
                            "type": "raid",
                            "file_system": "ext2",
                            "name": "Boot"
                        },
                        {
                            "type": "lvm_meta_pool",
                            "size": 64
                        },
                        {
                            "size": 0,
                            "type": "pv",
                            "lvm_meta_size": 0,
                            "vg": "os"
                        },
                        {
                            "size": 64971,
                            "type": "pv",
                            "lvm_meta_size": 64,
                            "vg": "image"
                        }
                    ],
                    "type": "disk",
                    "id": "disk/by-path/pci-0000:00:0d.0-scsi-0:0:0:0",
                    "size": 65535
                },
                {
                    "_allocate_size": "min",
                    "label": "Base System",
                    "min_size": 19374,
                    "volumes": [
                        {
                            "mount": "/",
                            "size": 15360,
                            "type": "lv",
                            "name": "root",
                            "file_system": "ext4"
                        },
                        {
                            "mount": "swap",
                            "size": 4014,
                            "type": "lv",
                            "name": "swap",
                            "file_system": "swap"
                        }
                    ],
                    "type": "vg",
                    "id": "os"
                },
                {
                    "_allocate_size": "min",
                    "label": "Zero size volume",
                    "min_size": 0,
                    "volumes": [
                        {
                            "mount": "none",
                            "size": 0,
                            "type": "lv",
                            "name": "zero_size",
                            "file_system": "xfs"
                        }
                    ],
                    "type": "vg",
                    "id": "zero_size"
                },
                {
                    "_allocate_size": "all",
                    "label": "Image Storage",
                    "min_size": 5120,
                    "volumes": [
                        {
                            "mount": "/var/lib/glance",
                            "size": 175347,
                            "type": "lv",
                            "name": "glance",
                            "file_system": "xfs"
                        }
                    ],
                    "type": "vg",
                    "id": "image"
                }
            ]
        },
        "mco_connector": "rabbitmq",
        "mco_host": "10.20.0.2",
        "user_accounts": [
            {
                "name": "fueladmin",
                "password": "fueladmin",
                "homedir": "/home/fueladmin",
                "sudo": [],
                "ssh_keys": []
            },
            {
                "name": "fuel",
                "password": "fuel",
                "homedir": "/var/lib/fuel",
                "sudo": ["ALL=(ALL) NOPASSWD: ALL"],
                "ssh_keys": []
            },
            {
                "name": "root",
                "password": "r00tme",
                "homedir": "/root",
                "ssh_keys": []
            }
        ]
    },
    "name": "node-1",
    "hostname": "node-1.domain.tld",
    "slave_name": "node-1",
    "power_pass": "/root/.ssh/bootstrap.rsa",
    "netboot_enabled": "1"
}

LIST_BLOCK_DEVICES_SAMPLE = [
    {'uspec':
        {'DEVLINKS': [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/ata-VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/wwn-fake_wwn_1',
            '/dev/disk/by-path/pci-0000:00:1f.2-scsi-0:0:0:0'],
         'ID_SERIAL_SHORT': 'fake_serial_1',
         'ID_WWN': 'fake_wwn_1',
         'DEVPATH': '/devices/pci0000:00/0000:00:1f.2/ata1/host0/'
                    'target0:0:0/0:0:0:0/block/sda',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sda',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/sda',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'
         },
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            '/dev/disk/by-id/ata-VBOX_HARDDISK_VBf2923215-708af674',
            '/dev/disk/by-id/scsi-SATA_VBOX_HARDDISK_VBf2923215-708af674',
            '/dev/disk/by-id/wwn-fake_wwn_2'],
         'ID_SERIAL_SHORT': 'fake_serial_2',
         'ID_WWN': 'fake_wwn_2',
         'DEVPATH': '/devices/pci0000:00/0000:00:3f.2/ata2/host0/'
                    'target0:0:0/0:0:0:0/block/sdb',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sdb',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/sdb',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'},
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            '/dev/disk/by-id/ata-VBOX_HARDDISK_VB50ee61eb-84e74fdf',
            '/dev/disk/by-id/scsi-SATA_VBOX_HARDDISK_VB50ee61eb-84e74fdf',
            '/dev/disk/by-id/wwn-fake_wwn_3',
            '/dev/disk/by-path/pci-0000:00:0d.0-scsi-0:0:0:0'],
         'ID_SERIAL_SHORT': 'fake_serial_3',
         'ID_WWN': 'fake_wwn_3',
         'DEVPATH': '/devices/pci0000:00/0000:00:0d.0/ata4/host0/target0:0:0/'
                    '0:0:0:0/block/sdc',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sdc',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'},
     'startsec': '0',
     'device': '/dev/sdc',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'},
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            '/dev/disk/by-id/by-id/md-fake-raid-uuid',
            ],
         'ID_SERIAL_SHORT': 'fake_serial_raid',
         'ID_WWN': 'fake_wwn_raid',
         'DEVPATH': '/devices/virtual/block/md123',
         'ID_MODEL': 'fake_raid',
         'DEVNAME': '/dev/md123',
         'MAJOR': '9',
         'DEVTYPE': 'disk', 'MINOR': '123'},
     'startsec': '0',
     'device': '/dev/md123',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'},
     'size': 500107862016},
]

LIST_BLOCK_DEVICES_SAMPLE_NVME = [
    {'uspec':
        {'DEVLINKS': [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/ata-VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/wwn-fake_wwn_1',
            '/dev/disk/by-path/pci-0000:00:1f.2-scsi-0:0:0:0'],
         'ID_SERIAL_SHORT': 'fake_serial_1',
         'ID_WWN': 'fake_wwn_1',
         'DEVPATH': '/devices/pci0000:00/0000:00:1f.2/ata1/host0/'
                    'target0:0:0/0:0:0:0/block/sda',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sda',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/sda',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'
         },
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            '/dev/block/253:0',
            '/dev/disk/by-path/pci-0000:04:00.0',
            '/dev/disk/by-id/wwn-0x65cd2e4080864356494e000000010000'],
         'DEVPATH': '/devices/pci:00/:00:04.0/block/nvme0n1',
         'DEVNAME': '/dev/nvme0n1',
         'MAJOR': '259',
         'DEVTYPE': 'disk', 'MINOR': '0',
         },
     'startsec': '0',
     'device': '/dev/nvme0n1',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'},
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            '/dev/block/253:64',
            '/dev/disk/by-path/pci-0000:05:00.0',
            '/dev/disk/by-id/wwn-0x65cd2e4080864356494e000000010000'],
         'DEVPATH': '/devices/pci:00/:00:04.0/block/nvme1n1',
         'DEVNAME': '/dev/nvme1n1',
         'MAJOR': '259',
         'DEVTYPE': 'disk', 'MINOR': '0',
         },
     'startsec': '0',
     'device': '/dev/nvme1n1',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'},
     'size': 500107862016},
]

LIST_BLOCK_DEVICES_MPATH = [
    {'uspec':
        {'DEVLINKS': [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/wwn-fake_wwn_1',
            '/dev/disk/by-path/pci-0000:00:1f.2-scsi-0:0:0:0'],
         'ID_SERIAL_SHORT': 'fake_serial_1',
         'ID_WWN': 'fake_wwn_1',
         'DEVPATH': '/devices/pci0000:00/0000:00:1f.2/ata1/host0/'
                    'target0:0:0/0:0:0:0/block/sda',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sda',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/sda',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'
         },
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/wwn-fake_wwn_1',
            '/dev/disk/by-path/pci-0000:00:1f.2-scsi-0:0:1:0'],
         'ID_SERIAL_SHORT': 'fake_serial_1',
         'ID_WWN': 'fake_wwn_1',
         'DEVPATH': '/devices/pci0000:00/0000:00:1f.2/ata1/host0/'
                    'target0:0:0/0:0:0:0/block/sdb',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sdb',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/sdb',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'
         },
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-b385c7cd',
            '/dev/disk/by-id/wwn-fake_wwn_1',
            '/dev/disk/by-id/dm-uuid-mpath-fake_wwn_1'
            ],
         'ID_SERIAL_SHORT': 'fake_serial_1',
         'ID_WWN': 'fake_wwn_1',
         'DEVPATH': '/devices/pci0000:00/0000:00:1f.2/ata1/host0/',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/dm-0',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/mapper/12312',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'
         },
     'size': 500107862016},
    {'uspec':
        {'DEVLINKS': [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-fffff',
            '/dev/disk/by-id/wwn-fake_wwn_2'
            '/dev/disk/by-path/pci-0000:00:1f.2-scsi-0:0:4:0'],
         'ID_SERIAL_SHORT': 'fake_serial_2',
         'ID_WWN': 'fake_wwn_1',
         'DEVPATH': '/devices/pci0000:00/0000:00:1f.2/ata2/host1/',
         'ID_MODEL': 'fake_id_model',
         'DEVNAME': '/dev/sdc',
         'MAJOR': '8',
         'DEVTYPE': 'disk', 'MINOR': '0', 'ID_BUS': 'ata'
         },
     'startsec': '0',
     'device': '/dev/sdc',
     'espec': {'state': 'running', 'timeout': '30', 'removable': '0'},
     'bspec': {
         'sz': '976773168', 'iomin': '4096', 'size64': '500107862016',
         'ss': '512', 'ioopt': '0', 'alignoff': '0', 'pbsz': '4096',
         'ra': '256', 'ro': '0', 'maxsect': '1024'
         },
     'size': 500107862016},
]

SINGLE_DISK_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root",
                "keep_data": True
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 102400
    }
]

SECOND_DISK_OS_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 102400
    },
    {
        "name": "sdb",
        "extra": ["sdb"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root",
                "keep_data": True
            },
        ],
        "type": "disk",
        "id": "sdb",
        "size": 102400
    }
]

MPATH_DISK_KS_SPACES = [
    {
        "name": "mapper/12312",
        "extra": [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-b385c7cd',
            'disk/by-id/wwn-fake_wwn_1'],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root",
            },
        ],
        "type": "disk",
        "id": "dm-0",
        "size": 102400
    },
    {
        "name": "sdc",
        "extra": [
            'disk/by-id/scsi-SATA_VBOX_HARDDISK_VB69050467-fffff',
            'disk/by-id/wwn-fake_wwn_2'],
        "free_space": 1024,
        "volumes": [
            {
                "mount": "/home",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root",
            },
        ],
        "type": "disk",
        "id": "sdc",
        "size": 102400
    }
]

NO_BOOT_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root"
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 102400
    }
]

MD_RAID_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "raid",
                "file_system": "ext4",
                "name": "Root"
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 102400
    }
]

FIRST_DISK_HUGE_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root"
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 2097153
    },
    {
        "name": "sdb",
        "extra": ["sdb"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/tmp",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "TMP"
            },
        ],
        "type": "disk",
        "id": "sdb",
        "size": 65535
    }
]

ONLY_ROOTFS_IMAGE_SPACES = [
    {
        "name": "sda",
        "extra": [],
        "free_space": 11000,
        "volumes": [
            {
                "mount": "/",
                "type": "partition",
                "file_system": "ext4",
                "size": 10000
            }
        ],
        "size": 11000,
        "type": "disk",
        "id": "sda",
    }
]

FIRST_DISK_NVME_KS_SPACES = [
    {
        "name": "nvme0n1",
        "extra": ["nvme0n1"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root"
            },
        ],
        "type": "disk",
        "id": "nvme0n1",
        "size": 97153
    },
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/tmp",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "TMP"
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 65535
    }
]

ONLY_ONE_NVME_KS_SPACES = [
    {
        "name": "nvme0n1",
        "extra": ["/dev/nvme0n1"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root"
            },
        ],
        "type": "disk",
        "id": "nvme0n1",
        "size": 97153
    },
]

MANY_HUGE_DISKS_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Root"
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 2097153
    },
    {
        "name": "sdb",
        "extra": ["sdb"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/tmp",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "TMP"
            },
        ],
        "type": "disk",
        "id": "sdb",
        "size": 2097153
    }
]

LVM_META_POOL_KS_SPACES = [
    {
        'name': 'sda',
        'volumes': [
            {
                'type': 'boot',
                'size': 300
            },
            {
                'mount': '/boot',
                'size': 200,
                'type': 'raid',
                'file_system': 'ext2',
                'name': 'Boot'
            },
            {
                'type': 'lvm_meta_pool',
                'size': 0
            },
            {
                'size': 40592,
                'type': 'pv',
                'lvm_meta_size': 64,
                'vg': 'os'
            },
            {
                'size': 61308,
                'type': 'pv',
                'lvm_meta_size': 64,
                'vg': 'vm'
            }
        ],
        'extra': [],
        'size': 102400,
        'type': 'disk',
        'id': 'sda',
        'free_space': 0
    },
    {
        'name': 'sdb',
        'volumes': [
            {
                'type': 'boot',
                'size': 300
            },
            {
                'mount': '/boot',
                'size': 200,
                'type': 'raid',
                'file_system': 'ext2',
                'name': 'Boot'
            },
            {
                'type': 'lvm_meta_pool',
                'size': 128
            },
            {
                'size': 0,
                'type': 'pv',
                'lvm_meta_size': 0,
                'vg': 'os'
            },
            {
                'size': 0,
                'type': 'pv',
                'lvm_meta_size': 0,
                'vg': 'vm'
            }
        ],
        'extra': [],
        'size': 2048,
        'type': 'disk',
        'id': 'sdb',
        'free_space': 1420
    },
    {
        'name': 'sdc',
        'volumes': [
            {
                'type': 'boot',
                'size': 300
            },
            {
                'mount': '/boot',
                'size': 200,
                'type': 'raid',
                'file_system': 'ext2',
                'name': 'Boot'
            },
            {
                'type': 'lvm_meta_pool',
                'size': 128},
            {
                'size': 0,
                'type': 'pv',
                'lvm_meta_size': 0,
                'vg': 'os'
            },
            {
                'size': 0,
                'type': 'pv',
                'lvm_meta_size': 0,
                'vg': 'vm'
            }
        ],
        'extra': [],
        'size': 358400,
        'type': 'disk',
        'id': 'sdc',
        'free_space': 357772
    },
    {
        'min_size': 40528,
        'volumes': [
            {
                'mount': '/',
                'size': 20480,
                'type': 'lv',
                'name': 'root',
                'file_system': 'ext4'
            },
            {
                'mount': 'swap',
                'size': 20048,
                'type': 'lv',
                'name': 'swap',
                'file_system': 'swap'
            }
        ],
        'type': 'vg',
        '_allocate_size': 'min',
        'id': 'os',
        'label': 'Base System'
    },
    {
        'min_size': 5120,
        'volumes': [
            {
                'mount': '/var/lib/nova',
                'size': 61244,
                'type': 'lv',
                'name': 'nova',
                'file_system': 'xfs'
            }
        ],
        'type': 'vg',
        '_allocate_size': 'all',
        'id': 'vm',
        'label': 'Virtual Storage'}
]

SINGLE_NVME_DISK_KS_SPACES = [
    {
        'extra': ['disk/by-id/wwn-0x65cd2e4080864356494e000000010000'],
        'free_space': 762469,
        'id': 'disk/by-path/pci-0000:05:00.0',
        'name': 'nvme0n1',
        'size': 763097,
        'type': 'disk',
        'volumes': [
            {'size': 300, 'type': 'boot'},
            {'file_system': 'ext2', 'mount': '/boot', 'name': 'Boot',
             'size': 200, 'type': 'raid'},
            {'size': 0, 'type': 'lvm_meta_pool'},
            {'lvm_meta_size': 64, 'size': 55360, 'type': 'pv', 'vg': 'os'},
            {'lvm_meta_size': 64, 'size': 707237, 'type': 'pv', 'vg': 'vm'}
        ]
    }
]


FAKE_RAID_DISK_KS_SPACES = [
    {
        "name": "sda",
        "extra": ["sda"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/var",
                "size": 200,
                "type": "partition",
                "file_system": "ext4",
                "name": "Var"
            },
        ],
        "type": "disk",
        "id": "sda",
        "size": 2097153
    },
    {
        "name": "sdb",
        "extra": ["sdb"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "mount": "/tmp",
                "size": 200,
                "type": "partition",
                "file_system": "ext2",
                "name": "TMP"
            },
        ],
        "type": "disk",
        "id": "sdb",
        "size": 2097153
    },
    {
        "name": "md123",
        "extra": ["md123"],
        "free_space": 1024,
        "volumes": [
            {
                "type": "boot",
                "size": 300
            },
            {
                "mount": "/boot",
                "size": 200,
                "type": "raid",
                "file_system": "ext2",
                "name": "Boot"
            },
            {
                "lvm_meta_size": 64,
                "size": 271370,
                "type": "pv",
                "vg": "os"
            },

        ],
        "type": "disk",
        "id": "md123",
        "size": 2097153
    },
    {
        "id": "os",
        "label": "Base System",
        "min_size": 55296,
        "type": "vg",
        "volumes": [
            {
                "file_system": "ext4",
                "mount": "/",
                "name": "root",
                "size": 267210,
                "type": "lv"
            },
            {
                "file_system": "swap",
                "mount": "swap",
                "name": "swap",
                "size": 4096,
                "type": "lv"
            }
        ],
    },
]


class TestNailgunMatch(unittest2.TestCase):
    def test_match_device_by_id_matches(self):
        # matches by 'by-id' links
        fake_ks_disk = {
            "extra": [
                "disk/by-id/fake_scsi_matches",
                "disk/by-id/fake_ata_dont_matches"
            ]
        }
        fake_hu_disk = {
            "uspec": {
                "DEVLINKS": [
                    "/dev/disk/by-id/fake_scsi_matches",
                    "/dev/disk/by-path/fake_path"
                ]
            }
        }
        self.assertTrue(nailgun.match_device(fake_hu_disk, fake_ks_disk))

    def test_match_device_id_dont_matches_non_empty_extra(self):
        # Shouldn't match. If non empty extra present it will match by what is
        # presented `extra` field, ignoring the `id` at all. Eg.: on VirtualBox
        fake_ks_disk = {
            "extra": [
                "disk/by-id/fake_scsi_dont_matches",
                "disk/by-id/fake_ata_dont_matches"
            ],
            "id": "sdd"
        }
        fake_hu_disk = {
            "uspec": {
                "DEVLINKS": [
                    "/dev/disk/by-id/fake_scsi_matches",
                    "/dev/disk/by-path/fake_path",
                    "/dev/sdd"
                ]
            }
        }
        self.assertFalse(nailgun.match_device(fake_hu_disk, fake_ks_disk))

    def test_match_device_id_matches_empty_extra(self):
        # since `extra` is empty, it will match by `id`
        fake_ks_disk = {
            "extra": [],
            "id": "sdd"
        }
        fake_hu_disk = {
            "uspec": {
                "DEVLINKS": [
                    "/dev/disk/by-id/fake_scsi_matches",
                    "/dev/disk/by-path/fake_path",
                    "/dev/sdd"
                ]
            }
        }
        self.assertTrue(nailgun.match_device(fake_hu_disk, fake_ks_disk))

    def test_match_device_id_matches_missing_extra(self):
        # `extra` is empty or just missing entirely, it will match by `id`
        fake_ks_disk = {"id": "sdd"}
        fake_hu_disk = {
            "uspec": {
                "DEVLINKS": [
                    "/dev/disk/by-id/fake_scsi_matches",
                    "/dev/disk/by-path/fake_path",
                    "/dev/sdd"
                ]
            }
        }
        self.assertTrue(nailgun.match_device(fake_hu_disk, fake_ks_disk))

    def test_match_device_dont_macthes(self):
        # Mismatches totally
        fake_ks_disk = {
            "extra": [
                "disk/by-id/fake_scsi_dont_matches",
                "disk/by-id/fake_ata_dont_matches"
            ],
            "id": "sda"
        }
        fake_hu_disk = {
            "uspec": {
                "DEVLINKS": [
                    "/dev/disk/by-id/fake_scsi_matches",
                    "/dev/disk/by-path/fake_path",
                    "/dev/sdd"
                ]
            }
        }
        self.assertFalse(nailgun.match_device(fake_hu_disk, fake_ks_disk))

    def test_match_device_dont_macthes_by_id(self):
        # disks are different but both of have same `by-path` link.
        # it will match by `extra` ignoring `id`
        fake_ks_disk = {
            "extra": [
                "disk/by-id/fake_scsi_dont_matches",
                "disk/by-id/fake_ata_dont_matches"
            ],
            "id": "disk/by-path/pci-fake_path"
        }
        fake_hu_disk = {
            "uspec": {
                "DEVLINKS": [
                    "/dev/disk/by-id/fake_scsi_matches",
                    "/dev/disk/by-path/pci-fake_path",
                    "/dev/sdd"
                ]
            }
        }
        self.assertFalse(nailgun.match_device(fake_hu_disk, fake_ks_disk))


class TestNailgunBootDisks(unittest2.TestCase):
    class PropertyMock(mock.Mock):
        def __get__(self, instance, owner):
            return self()

    nvme_disk = {
        'name': 'nvmen1', 'size': 5,
        'volumes': [{'type': 'raid', 'mount': '/boot', 'size': 1}],
    }
    disks = [
        {'name': 'sda', 'size': 5,
         'volumes': [{'type': 'partition', 'mount': '/boot',
                     'size': 1}],
         },
        {'name': 'sdb', 'size': 5,
         'volumes': [{'type': 'raid', 'mount': '/boot', 'size': 1}],
         },
    ]
    big_disk = {
        'name': '2big', 'size': 555555555,
        'volumes': [{'type': 'raid', 'mount': '/boot', 'size': 1}],
    }
    fake_raid = {
        'name': 'md123', 'size': 5,
        'volumes': [{'type': 'raid', 'mount': '/boot', 'size': 1},
                    {'type': 'pv', 'vg': 'os', 'size': 1}],
    }
    non_os_fake_raid = {
        'name': 'md456', 'size': 5,
        'volumes': [{'type': 'raid', 'mount': '/boot', 'size': 1},
                    {'type': 'pv', 'vg': 'image', 'size': 1}],
    }

    def _check_boot_disks(self, ks_disks_return_value,
                          not_expected_disk, expected_disks):
        with mock.patch.object(nailgun.Nailgun, '__init__', return_value=None):
            ks_disks = self.PropertyMock()
            with mock.patch.object(nailgun.Nailgun, 'ks_disks', ks_disks):
                drv = nailgun.Nailgun('fake_data')
                ks_disks.return_value = ks_disks_return_value
                self.assertNotIn(not_expected_disk, drv.boot_disks)
                self.assertEqual(expected_disks, drv.boot_disks)

    def test_md_boot_disk(self):
        ks_disks_return_value = self.disks + [self.non_os_fake_raid] +\
            [self.fake_raid]
        not_expected_disk = self.non_os_fake_raid
        expected_disks = [self.fake_raid]
        self._check_boot_disks(ks_disks_return_value, not_expected_disk,
                               expected_disks)

    def test_boot_disks_no_nvme(self):
        ks_disks_return_value = self.disks + [self.nvme_disk]
        not_expected_disk = self.nvme_disk
        expected_disks = self.disks
        self._check_boot_disks(ks_disks_return_value, not_expected_disk,
                               expected_disks)


@mock.patch.object(nailgun.Nailgun, '__init__', return_value=None)
class TestNailgunGetOSMethods(unittest2.TestCase):
    def test_parse_operating_system_test_profiles(self, mock_nailgun):
        d = {'centos-x86_64': {'obj': objects.Centos, 'minor': 5, 'major': 6},
             'centos7-x86_64': {'obj': objects.Centos, 'minor': 0, 'major': 7},
             'ubuntu_1204_x86_64': {'obj': objects.Ubuntu,
                                    'minor': 4, 'major': 12},
             'ubuntu_1404_x86_64': {'obj': objects.Ubuntu,
                                    'minor': 4, 'major': 14},
             'generic_os': {'obj': objects.OperatingSystem,
                            'minor': 'unknown', 'major': 'unknown'}}
        drv = nailgun.Nailgun('fake_data')
        for profile, obj in six.iteritems(d):
            os = drv.get_os_by_profile(profile)
            self.assertIsInstance(os, obj['obj'])
            self.assertEqual(obj['minor'], os.minor)
            self.assertEqual(obj['major'], os.major)

    def test_parse_operating_system_image_meta(self, mock_nailgun):
        d = {'Centos': objects.Centos,
             'Ubuntu': objects.Ubuntu,
             'unknown': None}
        drv = nailgun.Nailgun('fake_data')
        for os_name, obj in six.iteritems(d):
            os = drv.get_os_by_image_meta(
                {'name': os_name, 'minor': 1, 'major': 2})
            if os:
                self.assertIsInstance(os, obj)
                self.assertEqual(1, os.minor)
                self.assertEqual(2, os.major)
            else:
                self.assertIsNone(os)
                self.assertEqual('unknown', os_name)


@mock.patch.object(nailgun.Nailgun, 'parse_image_meta', return_value={})
@mock.patch('fuel_agent.drivers.nailgun.hu.list_block_devices')
class TestNailgunMockedMeta(unittest2.TestCase):
    def test_configdrive_scheme(self, mock_lbd, mock_image_meta):
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        cd_scheme = nailgun.Nailgun(PROVISION_SAMPLE_DATA).configdrive_scheme
        self.assertEqual(['fake_authorized_key1', 'fake_authorized_key2',
                          'fake_auth_key'], cd_scheme.common.ssh_auth_keys)
        self.assertEqual('node-1.domain.tld', cd_scheme.common.hostname)
        self.assertEqual('node-1.domain.tld', cd_scheme.common.fqdn)
        self.assertEqual('node-1.domain.tld', cd_scheme.common.fqdn)
        self.assertEqual('"10.20.0.2"', cd_scheme.common.name_servers)
        self.assertEqual('"domain.tld"', cd_scheme.common.search_domain)
        self.assertEqual('10.20.0.2', cd_scheme.common.master_ip)
        self.assertEqual('http://10.20.0.2:8000/api',
                         cd_scheme.common.master_url)
        self.assertEqual('08:00:27:79:da:80_eth0,08:00:27:46:43:60_eth1,'
                         '08:00:27:b1:d7:15_eth2', cd_scheme.common.udevrules)
        self.assertEqual('08:00:27:79:da:80', cd_scheme.common.admin_mac)
        self.assertEqual('10.20.0.3', cd_scheme.common.admin_ip)
        self.assertEqual('255.255.255.0', cd_scheme.common.admin_mask)
        self.assertEqual('eth0', cd_scheme.common.admin_iface_name)
        self.assertEqual('America/Los_Angeles', cd_scheme.common.timezone)
        self.assertEqual('fuel.domain.tld', cd_scheme.puppet.master)
        self.assertEqual('unset', cd_scheme.mcollective.pskey)
        self.assertEqual('mcollective', cd_scheme.mcollective.vhost)
        self.assertEqual('10.20.0.2', cd_scheme.mcollective.host)
        self.assertEqual('mcollective', cd_scheme.mcollective.user)
        self.assertEqual('marionette', cd_scheme.mcollective.password)
        self.assertEqual('rabbitmq', cd_scheme.mcollective.connector)
        self.assertEqual('pro_fi-le', cd_scheme.profile)
        self.assertEqual(
            [
                {
                    "name": "repo1",
                    "type": "deb",
                    "uri": "uri1",
                    "suite": "suite",
                    "section": "section",
                    "priority": 1001
                },
                {
                    "name": "repo2",
                    "type": "deb",
                    "uri": "uri2",
                    "suite": "suite",
                    "section": "section",
                    "priority": 1001
                }
            ],
            cd_scheme.common.ks_repos)

    def test_configdrive_scheme_set_cloud_init_templates(self, mock_lbd,
                                                         mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        expected_templates = 'fake_templates'
        data['ks_meta']['cloud_init_templates'] = expected_templates
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        cd_scheme = nailgun.Nailgun(data).configdrive_scheme
        self.assertEqual(expected_templates, cd_scheme.templates)

    def test_partition_scheme(self, mock_lbd, mock_image_meta):
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(PROVISION_SAMPLE_DATA)
        p_scheme = drv.partition_scheme
        self.assertEqual(5, len(p_scheme.fss))
        self.assertEqual(4, len(p_scheme.pvs))
        self.assertEqual(3, len(p_scheme.lvs))
        self.assertEqual(2, len(p_scheme.vgs))
        self.assertEqual(3, len(p_scheme.parteds))

    def test_parse_partition_scheme_for_nvme_disks(
            self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = (SINGLE_NVME_DISK_KS_SPACES +
                                                   SINGLE_DISK_KS_SPACES)
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE_NVME
        drv = nailgun.Nailgun(data)
        p_scheme = drv.partition_scheme
        self.assertEqual(2, len(p_scheme.parteds))

    def test_image_scheme(self, mock_lbd, mock_image_meta):
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(PROVISION_SAMPLE_DATA)
        p_scheme = drv.partition_scheme
        i_scheme = drv.image_scheme
        expected_images = []
        for fs in p_scheme.fss:
            if fs.mount not in PROVISION_SAMPLE_DATA['ks_meta']['image_data']:
                continue
            i_data = PROVISION_SAMPLE_DATA['ks_meta']['image_data'][fs.mount]
            expected_images.append(image.Image(
                uri=i_data['uri'],
                target_device=fs.device,
                format=i_data['format'],
                container=i_data['container'],
            ))
        expected_images = sorted(expected_images, key=lambda x: x.uri)
        for i, img in enumerate(sorted(i_scheme.images, key=lambda x: x.uri)):
            self.assertEqual(img.uri, expected_images[i].uri)
            self.assertEqual(img.target_device,
                             expected_images[i].target_device)
            self.assertEqual(img.format,
                             expected_images[i].format)
            self.assertEqual(img.container,
                             expected_images[i].container)
            self.assertIsNone(img.size)
            self.assertIsNone(img.md5)

    def test_image_scheme_with_checksums(self, mock_lbd, mock_image_meta):
        fake_image_meta = {
            'images': [{'raw_md5': 'fakeroot', 'raw_size': 1,
                        'container_name': 'fake_image.img.gz'}]}
        mock_image_meta.return_value = fake_image_meta
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        p_data = PROVISION_SAMPLE_DATA.copy()
        drv = nailgun.Nailgun(p_data)
        p_scheme = drv.partition_scheme
        i_scheme = drv.image_scheme
        expected_images = []
        for fs in p_scheme.fss:
            if fs.mount not in PROVISION_SAMPLE_DATA['ks_meta']['image_data']:
                continue
            i_data = PROVISION_SAMPLE_DATA['ks_meta']['image_data'][fs.mount]
            expected_images.append(image.Image(
                uri=i_data['uri'],
                target_device=fs.device,
                format=i_data['format'],
                container=i_data['container'],
            ))
        expected_images = sorted(expected_images, key=lambda x: x.uri)
        for i, img in enumerate(sorted(i_scheme.images, key=lambda x: x.uri)):
            self.assertEqual(img.uri, expected_images[i].uri)
            self.assertEqual(img.target_device,
                             expected_images[i].target_device)
            self.assertEqual(img.format,
                             expected_images[i].format)
            self.assertEqual(img.container,
                             expected_images[i].container)
            self.assertEqual(
                img.size, fake_image_meta['images'][0]['raw_size'])
            self.assertEqual(img.md5, fake_image_meta['images'][0]['raw_md5'])

    def test_disk_dev_not_found(self, mock_lbd, mock_image_meta):
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(PROVISION_SAMPLE_DATA)
        fake_ks_disk = {
            "name": "fake",
            "extra": [
                "disk/by-id/fake_scsi_matches",
                "disk/by-id/fake_ata_dont_matches"
            ]
        }
        self.assertRaises(errors.DiskNotFoundError, drv._disk_dev,
                          fake_ks_disk)

    def test_get_partition_count(self, mock_lbd, mock_image_meta):
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(PROVISION_SAMPLE_DATA)
        self.assertEqual(3, drv._get_partition_count('Boot'))
        self.assertEqual(1, drv._get_partition_count('TMP'))

    def test_partition_scheme_no_mount_fs(self, mock_lbd, mock_image_meta):
        p_data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        for i in range(0, 3):
            p_data['ks_meta']['pm_data']['ks_spaces'][i]['volumes'].append(
                SWIFT)
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(p_data)
        p_scheme = drv.partition_scheme
        self.assertEqual(4, len(list(p_scheme.fss_w_mountpoints)))
        self.assertEqual(8, len(p_scheme.fss))
        self.assertEqual(4, len(p_scheme.pvs))
        self.assertEqual(3, len(p_scheme.lvs))
        self.assertEqual(2, len(p_scheme.vgs))
        self.assertEqual(3, len(p_scheme.parteds))
        self.assertEqual(3, drv._get_partition_count('swift-storage'))

    def test_partition_scheme_ceph(self, mock_lbd, mock_image_meta):
        # TODO(agordeev): perform better testing of ceph logic
        p_data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        for i in range(0, 3):
            p_data['ks_meta']['pm_data']['ks_spaces'][i]['volumes'].append(
                CEPH_JOURNAL)
            p_data['ks_meta']['pm_data']['ks_spaces'][i]['volumes'].append(
                CEPH_DATA)
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(p_data)
        p_scheme = drv.partition_scheme
        self.assertEqual(4, len(list(p_scheme.fss_w_mountpoints)))
        self.assertEqual(5, len(p_scheme.fss))
        self.assertEqual(4, len(p_scheme.pvs))
        self.assertEqual(3, len(p_scheme.lvs))
        self.assertEqual(2, len(p_scheme.vgs))
        self.assertEqual(3, len(p_scheme.parteds))
        self.assertEqual(3, drv._get_partition_count('ceph'))
        # NOTE(agordeev): (-2, -1, -1) is the list of ceph data partition
        # counts corresponding to (sda, sdb, sdc) disks respectively.
        for disk, part in enumerate((-2, -1, -1)):
            self.assertEqual(CEPH_DATA['partition_guid'],
                             p_scheme.parteds[disk].partitions[part].guid)

    def test_grub_stage1_on_all_disks(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = FIRST_DISK_HUGE_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        for parted in drv.partition_scheme.parteds:
            # check that the first partition was created for stage1
            # it should have very specific flag 'bios_grub'
            self.assertIn('bios_grub', parted.partitions[0].flags)

    def test_grub_centos_26(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['profile'] = 'centos'
        data['ks_meta']['kernel_lt'] = 0
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(drv.grub.kernel_params,
                         ' ' + data['ks_meta']['pm_data']['kernel_params'])
        self.assertEqual(drv.grub.kernel_regexp, r'^vmlinuz-2\.6.*')
        self.assertEqual(drv.grub.initrd_regexp, r'^initramfs-2\.6.*')
        self.assertEqual(1, drv.grub.version)
        self.assertIsNone(drv.grub.kernel_name)
        self.assertIsNone(drv.grub.initrd_name)

    def test_grub_centos_lt(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['profile'] = 'centos'
        data['ks_meta']['kernel_lt'] = 1
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(drv.grub.kernel_params,
                         ' ' + data['ks_meta']['pm_data']['kernel_params'])
        self.assertIsNone(drv.grub.kernel_regexp)
        self.assertIsNone(drv.grub.initrd_regexp)
        self.assertEqual(1, drv.grub.version)
        self.assertIsNone(drv.grub.kernel_name)
        self.assertIsNone(drv.grub.initrd_name)

    def test_grub_ubuntu(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['profile'] = 'ubuntu'
        data['ks_meta']['kernel_lt'] = 0
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(drv.grub.kernel_params,
                         ' ' + data['ks_meta']['pm_data']['kernel_params'])
        self.assertEqual(2, drv.grub.version)
        self.assertIsNone(drv.grub.kernel_regexp)
        self.assertIsNone(drv.grub.initrd_regexp)
        self.assertIsNone(drv.grub.kernel_name)
        self.assertIsNone(drv.grub.initrd_name)

    def test_boot_partition_ok_single_disk(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = SINGLE_DISK_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/sda3')

    def test_boot_partition_bootable_flag(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'][1]['bootable'] = True
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/sdb3')

    def test_elevate_keep_data_single_disk(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = SINGLE_DISK_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertTrue(drv.partition_scheme.fs_by_mount('/').keep_data)

        for parted in drv.partition_scheme.parteds:
            for partition in parted.partitions:
                self.assertFalse(partition.keep_data)

        for md in drv.partition_scheme.mds:
            self.assertFalse(md.keep_data)

        for pv in drv.partition_scheme.pvs:
            self.assertFalse(pv.keep_data)

        for vg in drv.partition_scheme.vgs:
            self.assertFalse(vg.keep_data)

        for lv in drv.partition_scheme.lvs:
            self.assertFalse(lv.keep_data)

        for fs in drv.partition_scheme.fss:
            if fs.mount != '/':
                self.assertFalse(fs.keep_data)

    def test_configdrive_partition_on_os_disk(self, mock_lbd,
                                              mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = SECOND_DISK_OS_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        root_device = drv.partition_scheme.root_device()[:-1]
        self.assertIn(root_device, drv.partition_scheme.configdrive_device())
        self.assertEqual('/dev/sdb', root_device)

    @mock.patch.object(nailgun.Nailgun, '_needs_configdrive',
                       return_value=False)
    def test_configdrive_partition_not_needed(self, mock_cdrive, mock_lbd,
                                              mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertIsNone(drv.partition_scheme.configdrive_device())

    def test_boot_partition_ok_many_normal_disks(self, mock_lbd,
                                                 mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/sda3')

    def test_boot_partition_ok_first_disk_huge(self, mock_lbd,
                                               mock_image_meta):
        # /boot should be on first disk even if it's huge
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = FIRST_DISK_HUGE_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/sda3')

    def test_boot_partition_ok_many_huge_disks(self, mock_lbd,
                                               mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = MANY_HUGE_DISKS_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/sda3')

    def test_boot_partition_and_rootfs_on_fake_raid(self, mock_lbd,
                                                    mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = FAKE_RAID_DISK_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/md123p3')

    def test_boot_partition_no_boot(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = NO_BOOT_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/').device,
            '/dev/sda3')
        # there's no boot partition is scheme.
        # It is not expected to be created
        self.assertIsNone(drv.partition_scheme.fs_by_mount('/boot'))

    def test_boot_partition_no_boot_nvme(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = ONLY_ONE_NVME_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE_NVME
        with self.assertRaisesRegexp(
                errors.WrongPartitionSchemeError,
                '/boot partition has not been created for some reasons'):
            nailgun.Nailgun(data)

    def test_boot_partition_is_not_on_nvme(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = FIRST_DISK_NVME_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE_NVME
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/boot').device,
            '/dev/sda3')

    def test_boot_partition_is_on_rootfs_nailgun(self, mock_lbd,
                                                 mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = ONLY_ROOTFS_IMAGE_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE_NVME
        drv = nailgun.Nailgun(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/').device,
            '/dev/sda3')
        self.assertIsNone(drv.partition_scheme.fs_by_mount('/boot'))

    def test_unallocated_disks_lvm_meta(self, mock_lbd, mock_image_meta):
        # even if a disk contains /boot partition or lvm_meta_pool volume
        # it still should be considered as unallocated.
        # these things are just leftovers from volume manager.
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = LVM_META_POOL_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        for parted in drv.partition_scheme.parteds:
            self.assertNotIn(parted.name, ['/dev/sdb', '/dev/sdc'])

    def test_boot_partition_is_on_rootfs_ironic(self, mock_lbd,
                                                mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['ks_meta']['pm_data']['ks_spaces'] = ONLY_ROOTFS_IMAGE_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE_NVME
        drv = nailgun.Ironic(data)
        self.assertEqual(
            drv.partition_scheme.fs_by_mount('/').device,
            '/dev/sda3')
        self.assertIsNone(drv.partition_scheme.fs_by_mount('/boot'))

    def test_md_metadata_centos(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['profile'] = 'base-centos-x86_64'
        data['ks_meta']['pm_data']['ks_spaces'] = MD_RAID_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(1, drv.grub.version)
        self.assertEqual(1, len(drv.partition_scheme.mds))
        self.assertEqual('0.90', drv.partition_scheme.mds[0].metadata)

    def test_md_metadata_centos70(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['profile'] = 'base-centos7-x86_64'
        data['ks_meta']['pm_data']['ks_spaces'] = MD_RAID_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(2, drv.grub.version)
        self.assertEqual(1, len(drv.partition_scheme.mds))
        self.assertEqual('default', drv.partition_scheme.mds[0].metadata)

    def test_md_metadata_ubuntu(self, mock_lbd, mock_image_meta):
        data = copy.deepcopy(PROVISION_SAMPLE_DATA)
        data['profile'] = 'base-ubuntu_1404_x86_64'
        data['ks_meta']['pm_data']['ks_spaces'] = MD_RAID_KS_SPACES
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        drv = nailgun.Nailgun(data)
        self.assertEqual(1, len(drv.partition_scheme.mds))
        self.assertEqual(2, drv.grub.version)
        self.assertEqual('default', drv.partition_scheme.mds[0].metadata)


@mock.patch.object(utils, 'init_http_request')
@mock.patch('fuel_agent.drivers.nailgun.hu.list_block_devices')
class TestNailgunImageMeta(unittest2.TestCase):
    def test_parse_image_meta(self, mock_lbd, mock_http_req):
        fake_image_meta = {'images': [{'raw_md5': 'fakeroot', 'raw_size': 1,
                                       'container_name': 'fake_image.img.gz'}]}
        prop_mock = mock.PropertyMock(return_value=yaml.dump(fake_image_meta))
        type(mock_http_req.return_value).text = prop_mock
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        p_data = PROVISION_SAMPLE_DATA.copy()
        drv = nailgun.Nailgun(p_data)
        self.assertEqual(fake_image_meta, drv._image_meta)
        mock_http_req.assert_called_once_with(
            'http://fake.host.org:123/imgs/fake_image.yaml')

    def test_parse_image_meta_not_parsed(self, mock_lbd, mock_http_req):
        mock_http_req.side_effect = KeyError()
        mock_lbd.return_value = LIST_BLOCK_DEVICES_SAMPLE
        p_data = PROVISION_SAMPLE_DATA.copy()
        drv = nailgun.Nailgun(p_data)
        self.assertEqual({}, drv._image_meta)
        mock_http_req.assert_called_once_with(
            'http://fake.host.org:123/imgs/fake_image.yaml')

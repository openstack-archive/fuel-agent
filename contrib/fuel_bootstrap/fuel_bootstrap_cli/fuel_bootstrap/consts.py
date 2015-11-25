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


# These consts shouldn't be configured

# TODO(asvechnikov): add possibility to specify custom config file
CONFIG_FILE = "/etc/fuel-agent/fuel_bootstrap_cli.yaml"
METADATA_FILE = "metadata.yaml"
CONTAINER_FORMAT = "tar.gz"
ROOTFS = {'name': 'rootfs',
          'mask': 'rootfs',
          'compress_format': 'xz',
          'uri': 'http://127.0.0.1:8080/bootstraps/{uuid}/root.squashfs',
          'format': 'ext4',
          'container': 'raw'}
BOOTSTRAP_MODULES = [
    {'name': 'kernel',
     'mask': 'kernel',
     'uri': 'http://127.0.0.1:8080/bootstraps/{uuid}/vmlinuz'},
    {'name': 'initrd',
     'mask': 'initrd',
     'compress_format': 'xz',
     'uri': 'http://127.0.0.1:8080/bootstraps/{uuid}/initrd.img'},
    ROOTFS
]

IMAGE_DATA = {'/': ROOTFS}

UBUNTU_RELEASE = 'trusty'

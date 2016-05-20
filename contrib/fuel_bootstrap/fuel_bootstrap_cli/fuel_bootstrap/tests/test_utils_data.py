# -*- coding: utf-8 -*-

#    Copyright 2016 Mirantis, Inc.
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
import os

import mock
import six
import unittest

from fuel_bootstrap import consts
from fuel_bootstrap import errors
from fuel_bootstrap.utils import data as bs_data

DATA = {'ubuntu_release': 'trusty',
        'repos': ['deb http://archive.ubuntu.com/ubuntu suite'],
        'post_script_file': None,
        'root_ssh_authorized_file': '/root/test',
        'extra_dirs': ['/test_extra_dirs'],
        'packages': [],
        'label': None,
        'no_default_extra_dirs': True,
        'no_default_packages': True,
        'extend_kopts': 'test_extend_kopts',
        'kernel_flavor': 'test_kernel_flavor',
        'output_dir': '/test_dir',
        'certs': None,
        'root_password': '1234567_abc'
        }

BOOTSTRAP_MODULES = [
    {'name': 'kernel',
     'mask': 'kernel',
     'uri': 'http://127.0.0.1:8080/bootstraps/123/vmlinuz'},
    {'name': 'initrd',
     'mask': 'initrd',
     'compress_format': 'xz',
     'uri': 'http://127.0.0.1:8080/bootstraps/123/initrd.img'},
    {'name': 'rootfs',
     'mask': 'rootfs',
     'compress_format': 'xz',
     'uri': 'http://127.0.0.1:8080/bootstraps/123/root.squashfs',
     'format': 'ext4',
     'container': 'raw'}
]

REPOS = [{'name': 'repo_0',
          'type': 'deb',
          'uri': 'http://archive.ubuntu.com/ubuntu',
          'priority': None,
          'suite': 'suite',
          'section': ''}]

IMAGE_DATA = {'/': {'name': 'rootfs',
                    'mask': 'rootfs',
                    'compress_format': 'xz',
                    'uri': 'http://127.0.0.1:8080/bootstraps/123/'
                           'root.squashfs',
                    'format': 'ext4',
                    'container': 'raw'}}

UUID = six.text_type(123)


class DataBuilderTestCase(unittest.TestCase):
    @mock.patch('uuid.uuid4', return_value=UUID)
    def setUp(self, uuid):
        super(DataBuilderTestCase, self).setUp()
        self.bd_builder = bs_data.BootstrapDataBuilder(DATA)

    def test_build(self):
        proxy_settings = {}
        file_name = "{0}.{1}".format(UUID, consts.COMPRESSED_CONTAINER_FORMAT)
        packages = [DATA.get('kernel_flavor')]
        bootstrap = {
            'bootstrap': {
                'modules': BOOTSTRAP_MODULES,
                'extend_kopts': DATA.get('extend_kopts'),
                'post_script_file': DATA.get('post_script_file'),
                'uuid': UUID,
                'extra_files': DATA.get('extra_dirs'),
                'root_ssh_authorized_file':
                    DATA.get('root_ssh_authorized_file'),
                'container': {
                    'meta_file': consts.METADATA_FILE,
                    'format': consts.COMPRESSED_CONTAINER_FORMAT
                },
                'label': UUID,
                'certs': DATA.get('certs')
            },
            'repos': REPOS,
            'proxies': proxy_settings,
            'codename': DATA.get('ubuntu_release'),
            'output': os.path.join(DATA.get('output_dir'), file_name),
            'packages': packages,
            'image_data': IMAGE_DATA,
            'hashed_root_password': None,
            'root_password': DATA.get('root_password')
        }
        data = self.bd_builder.build()
        self.assertEqual(data, bootstrap)

    def test_get_extra_dirs_no_default(self):
        result = self.bd_builder._get_extra_dirs()
        self.assertEqual(result, DATA.get('extra_dirs'))

    @mock.patch.object(bs_data, 'CONF')
    def test_get_extra_dirs(self, conf_mock):
        self.bd_builder.no_default_extra_dirs = False
        conf_mock.extra_dirs = ['/conf_test_extra_dirs']
        result = self.bd_builder._get_extra_dirs()
        six.assertCountEqual(self, result, DATA.get('extra_dirs') +
                             ['/conf_test_extra_dirs'])

    def test_prepare_modules(self):
        result = self.bd_builder._prepare_modules()
        self.assertEqual(result, BOOTSTRAP_MODULES)

    def test_prepare_image_data(self):
        result = self.bd_builder._prepare_image_data()
        self.assertEqual(result, IMAGE_DATA)

    def test_get_no_proxy_settings(self):
        self.assertEqual(self.bd_builder._get_proxy_settings(), {})

    @mock.patch.object(bs_data, 'CONF')
    def test_get_proxy_settings(self, conf_mock):
        conf_mock.direct_repo_addresses = None
        self.bd_builder.http_proxy = '127.0.0.1'
        self.bd_builder.https_proxy = '127.0.0.2'
        self.bd_builder.direct_repo_addr = ['127.0.0.3']
        proxy = {'protocols': {'http': self.bd_builder.http_proxy,
                               'https': self.bd_builder.https_proxy},
                 'direct_repo_addr_list': self.bd_builder.direct_repo_addr}
        result = self.bd_builder._get_proxy_settings()
        self.assertEqual(result, proxy)

    def test_get_direct_repo_addr_no_default(self):
        self.bd_builder.no_default_direct_repo_addr = True
        self.bd_builder.direct_repo_addr = ['127.0.0.3']
        result = self.bd_builder._get_direct_repo_addr()
        self.assertEqual(result, self.bd_builder.direct_repo_addr)

    @mock.patch.object(bs_data, 'CONF')
    def test_get_direct_repo_addr_conf(self, conf_mock):
        self.bd_builder.direct_repo_addr = ['127.0.0.3']
        conf_mock.direct_repo_addresses = ['127.0.0.4']
        result = self.bd_builder._get_direct_repo_addr()
        six.assertCountEqual(self, result,
                             self.bd_builder.direct_repo_addr + ['127.0.0.4'])

    @mock.patch.object(bs_data, 'CONF')
    def test_get_direct_repo_addr(self, conf_mock):
        conf_mock.direct_repo_addresses = None
        self.bd_builder.direct_repo_addr = ['127.0.0.3']
        result = self.bd_builder._get_direct_repo_addr()
        self.assertEqual(result, self.bd_builder.direct_repo_addr)

    @mock.patch.object(bs_data, 'CONF')
    def test_get_repos_conf(self, conf_mock):
        self.bd_builder.repos = []
        conf_mock.repos = REPOS
        self.assertEqual(self.bd_builder._get_repos(), conf_mock.repos)

    @mock.patch.object(bs_data, 'CONF')
    def test_get_repos(self, conf_mock):
        conf_mock.repos = None
        self.assertEqual(self.bd_builder._get_repos(), REPOS)

    def test_get_packages_no_default(self):
        packages = copy.copy(DATA.get('packages'))
        packages.append(DATA.get('kernel_flavor'))
        six.assertCountEqual(self, self.bd_builder._get_packages(), packages)

    @mock.patch.object(bs_data, 'CONF')
    def test_get_packages(self, conf_mock):
        self.bd_builder.packages = ['test_package']
        self.bd_builder.no_default_packages = False
        conf_mock.packages = ['conf_package']
        result_packages = (self.bd_builder.packages + conf_mock.packages
                           + [DATA.get('kernel_flavor')])
        six.assertCountEqual(self, self.bd_builder._get_packages(),
                             result_packages)

    def parse_incorrect(self, repo):
        name = 'repo_0'
        error_msg = "Couldn't parse repository '{0}'".format(repo)
        with self.assertRaises(errors.IncorrectRepository, msg=error_msg):
            bs_data.BootstrapDataBuilder._parse_repo(repo, name)

    def test_parse_incorrect_type(self):
        repo = 'deb-false http://archive.ubuntu.com/ubuntu codename'
        self.parse_incorrect(repo)

    def test_parse_empty_uri(self):
        repo = 'deb codename'
        self.parse_incorrect(repo)

    def test_parse_empty_suite(self):
        repo = 'deb http://archive.ubuntu.com/ubuntu'
        self.parse_incorrect(repo)

    def parse_correct(self, repo, return_repo):
        name = 'repo_0'
        result = bs_data.BootstrapDataBuilder._parse_repo(repo, name)
        self.assertEqual(result, return_repo)

    def test_parse_correct_necessary(self):
        repo = DATA.get('repos')[0]
        self.parse_correct(repo, REPOS[0])

    def test_parse_correct_section(self):
        repo = 'deb http://archive.ubuntu.com/ubuntu suite section'
        return_repo = copy.deepcopy(REPOS[0])
        return_repo['section'] = 'section'
        self.parse_correct(repo, return_repo)

    def test_parse_correct_priority(self):
        repo = 'deb http://archive.ubuntu.com/ubuntu suite ,1'
        return_repo = copy.deepcopy(REPOS[0])
        return_repo['priority'] = '1'
        self.parse_correct(repo, return_repo)

    def test_parse_correct_all(self):
        repo = 'deb http://archive.ubuntu.com/ubuntu suite section,1'
        return_repo = copy.deepcopy(REPOS[0])
        return_repo['section'] = 'section'
        return_repo['priority'] = '1'
        self.parse_correct(repo, return_repo)

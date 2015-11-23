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
import os
import re
import six
import uuid
import yaml

from fuel_bootstrap import consts
from fuel_bootstrap import errors


class BootstrapDataBuilder(object):

    def __init__(self, data):
        self.astute = self._parse_astute()

        self.uuid = six.text_type(uuid.uuid4())

        self.container_format = consts.CONTAINER_FORMAT

        self.ubuntu_release = data.ubuntu_release or consts.UBUNTU_RELEASE
        self.ubuntu_repo = data.ubuntu_repo
        self.mos_repo = data.mos_repo
        self.repos = data.repos or []

        self.http_proxy = data.http_proxy or \
            self.astute['BOOTSTRAP']['HTTP_PROXY']
        self.https_proxy = data.https_proxy or \
            self.astute['BOOTSTRAP']['HTTPS_PROXY']
        self.direct_repo_addr = data.direct_repo_addr

        self.post_script_file = data.post_script_file
        self.root_ssh_authorized_file = data.root_ssh_authorized_file
        self.extra_files = data.extra_files

        self.include_kernel_module = data.include_kernel_module
        self.blacklist_kernel_module = data.blacklist_kernel_module

        self.packages = data.packages

        self.label = data.label
        self.extend_kopts = data.extend_kopts
        self.kernel_flavor = data.kernel_flavor
        self.output = os.path.join(
            data.output_dir,
            "{uuid}.{format}".format(
                uuid=self.uuid,
                format=self.container_format))

    def _parse_astute(self):
        with open(consts.ASTUTE_FILE) as f:
            data = yaml.safe_load(f)
        return data

    def build(self):
        return {
            'bootstrap': {
                'modules': self._prepare_modules(),
                'extend_kopts': self.extend_kopts,
                'post_script_file': self.post_script_file,
                'uuid': self.uuid,
                'extra_files': self.extra_files,
                'root_ssh_authorized_file': self.root_ssh_authorized_file,
                'container': {
                    'meta_file': consts.METADATA_FILE,
                    'format': self.container_format
                }
            },
            'repos': self._get_repos(),
            'proxies': self._get_proxy_settings(),
            'codename': self.ubuntu_release,
            'output': self.output,
            'packages': self._get_packages(),
            'image_data': self._prepare_image_data()
        }

    def _prepare_modules(self):
        modules = copy.copy(consts.BOOTSTRAP_MODULES)
        for module in modules:
            module['uri'] = module['uri'].format(uuid=self.uuid)
        return modules

    def _prepare_image_data(self):
        image_data = copy.copy(consts.IMAGE_DATA)
        image_data['/']['uri'] = image_data['/']['uri'].format(uuid=self.uuid)
        return image_data

    def _get_proxy_settings(self):
        if self.http_proxy or self.https_proxy:
            return {'protocols': {'http': self.http_proxy,
                                  'https': self.https_proxy},
                    'direct_repo_addr_list': self._get_direct_repo_addr()}
        return {}

    def _get_direct_repo_addr(self):
        addrs = set()
        if self.direct_repo_addr:
            addrs |= set(self.direct_repo_addr)

        addrs.add(self.astute['ADMIN_NETWORK']['ipaddress'])

        return list(addrs)

    def _get_repos(self):
        repos = []
        if self.ubuntu_repo:
            repos.extend(self._parse_ubuntu_repos(self.ubuntu_repo))
        else:
            repos.extend(self.astute['BOOTSTRAP']['MIRROR_DISTRO'])

        if self.mos_repo:
            repos.extend(self._parse_mos_repos(self.mos_repo))
        else:
            repos.extend(self.astute['BOOTSTRAP']['MIRROR_MOS'])

        repo_count = 0
        for repo in self.repos:
            repo_count += 1
            repos.append(self._parse_repo(
                repo,
                name="extra_repo{0}".format(repo_count)))

        if not self.repos:
            repos.extend(self.astute['BOOTSTRAP']['EXTRA_DEB_REPOS'])

        return sorted(repos, key=lambda repo: repo['priority'] or 500)

    def _get_packages(self):
        result = set(consts.DEFAULT_PACKAGES)
        result.add(self.kernel_flavor)
        if self.packages:
            result |= set(self.packages)
        return list(result)

    @classmethod
    def _parse_not_extra_repo(cls, repo):
        regexp = r"(?P<uri>[^\s]+) (?P<suite>[^\s]+)"

        match = re.match(regexp, repo)

        if not match:
            raise errors.IncorrectRepository(
                "Coulnd't parse ubuntu repository {0}".
                format(repo)
            )

        return match.group('uri', 'suite')

    @classmethod
    def _parse_mos_repos(cls, repo):
        uri, suite = cls._parse_not_extra_repo(repo)

        result = cls._generate_repos_from_uri(
            uri=uri,
            codename=suite,
            name='mos',
            components=['', '-updates', '-security'],
            section='main restricted',
            priority='1050'
        )
        result += cls._generate_repos_from_uri(
            uri=uri,
            codename=suite,
            name='mos',
            components=['-holdback'],
            section='main restricted',
            priority='1100'
        )
        return result

    @classmethod
    def _parse_ubuntu_repos(cls, repo):
        uri, suite = cls._parse_not_extra_repo(repo)

        return cls._generate_repos_from_uri(
            uri=uri,
            codename=cls.ubuntu_release,
            name='ubuntu',
            components=['', '-updates', '-security'],
            section='main universe multiverse'
        )

    @classmethod
    def _generate_repos_from_uri(cls, uri, codename, name, components=None,
                                 section=None, type_=None, priority=None):
        if not components:
            components = ['']
        result = []
        for component in components:
            result.append({
                "name": "{0}{1}".format(name, component),
                "type": type_ or "deb",
                "uri": uri,
                "priority": priority,
                "section": section,
                "suite": "{0}{1}".format(codename, component)
            })
        return result

    @classmethod
    def _parse_repo(cls, repo, name=None):
        regexp = r"(?P<type>deb(-src)?) (?P<uri>[^\s]+) (?P<suite>[^\s]+)( "\
                 r"(?P<section>[\w\s]*))?(,(?P<priority>[\d]+))?"

        match = re.match(regexp, repo)

        if not match:
            raise errors.IncorrectRepository("Couldn't parse repository '{0}'"
                                             .format(repo))

        repo_type = match.group('type')
        repo_suite = match.group('suite')
        repo_section = match.group('section')
        repo_uri = match.group('uri')
        repo_priority = match.group('priority')

        return {'name': name,
                'type': repo_type,
                'uri': repo_uri,
                'priority': repo_priority,
                'suite': repo_suite,
                'section': repo_section or ''}

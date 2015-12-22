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

from fuel_bootstrap import consts
from fuel_bootstrap import errors
from fuel_bootstrap import settings

CONF = settings.Configuration()


class BootstrapDataBuilder(object):

    def __init__(self, data):
        self.uuid = six.text_type(uuid.uuid4())

        self.container_format = consts.CONTAINER_FORMAT

        self.ubuntu_release = \
            data.get('ubuntu_release') or \
            consts.UBUNTU_RELEASE

        self.ubuntu_repo = data.get('ubuntu_repo')
        self.mos_repo = data.get('mos_repo')
        self.extra_repos = data.get('extra_repos') or []

        self.http_proxy = data.get('http_proxy') or CONF.http_proxy
        self.https_proxy = data.get('https_proxy') or CONF.https_proxy
        self.direct_repo_addr = data.get('direct_repo_addr') or []
        self.no_default_direct_repo_addr = data.get(
            'no_default_direct_repo_addr')

        self.post_script_file = \
            data.get('post_script_file') or \
            CONF.post_script_file
        self.root_ssh_authorized_file = \
            data.get('root_ssh_authorized_file') or \
            CONF.root_ssh_authorized_file
        self.extra_dirs = data.get('extra_dirs') or []
        self.no_default_extra_dirs = data.get('no_default_extra_dirs')

        self.packages = data.get('packages') or []
        self.no_default_packages = data.get('no_default_packages')

        self.label = data.get('label') or self.uuid
        self.extend_kopts = data.get('extend_kopts') or CONF.extend_kopts
        self.kernel_flavor = data.get('kernel_flavor') or CONF.kernel_flavor

        file_name = "{0}.{1}".format(self.uuid, self.container_format)
        output_dir = data.get('output_dir', CONF.output_dir)
        self.output = os.path.join(output_dir, file_name)

    def build(self):
        return {
            'bootstrap': {
                'modules': self._prepare_modules(),
                'extend_kopts': self.extend_kopts,
                'post_script_file': self.post_script_file,
                'uuid': self.uuid,
                'extra_files': self._get_extra_dirs(),
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

    def _get_extra_dirs(self):
        if self.no_default_extra_dirs:
            return self.extra_dirs
        dirs = set(self.extra_dirs)
        if CONF.extra_dirs:
            dirs |= set(CONF.extra_dirs)
        return list(dirs)

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
        if self.no_default_direct_repo_addr:
            return self.direct_repo_addr
        addrs = set(self.direct_repo_addr)
        if CONF.direct_repo_addresses:
            addrs |= set(CONF.direct_repo_addresses)

        return list(addrs)

    def _get_repos(self):
        repos = []
        if self.ubuntu_repo:
            repos.extend(self._parse_ubuntu_repos(self.ubuntu_repo))
        else:
            repos.extend(CONF.ubuntu_repos)

        if self.mos_repo:
            repos.extend(self._parse_mos_repos(self.mos_repo))
        else:
            repos.extend(CONF.mos_repos)

        repo_count = 0
        for repo in self.extra_repos:
            repo_count += 1
            repos.append(self._parse_repo(
                repo,
                name="extra_repo{0}".format(repo_count)))

        if not self.extra_repos and CONF.extra_repos:
            repos.extend(CONF.extra_repos)

        return repos

    def _get_packages(self):
        result = set(self.packages)
        result.add(self.kernel_flavor)
        if not self.no_default_packages and CONF.packages:
            result |= set(CONF.packages)
        return list(result)

    def _parse_ubuntu_repos(self, repo):
        uri, suite = self._parse_not_extra_repo(repo)

        return self._generate_repos_from_uri(
            uri=uri,
            codename=self.ubuntu_release,
            name='ubuntu',
            components=['', '-updates', '-security'],
            section='main universe multiverse'
        )

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

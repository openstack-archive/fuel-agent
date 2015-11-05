# Copyright 2015 Mirantis, Inc.
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


class Repo(object):
    def __init__(self, name, uri, priority=None):
        self.name = name
        self.uri = uri
        self.priority = priority


class DEBRepo(Repo):
    def __init__(self, name, uri, suite, section, meta=None, priority=None):
        super(DEBRepo, self).__init__(name, uri, priority)
        self.suite = suite
        self.section = section
        self.meta = meta


class RepoProxies(object):
    def __init__(self, proxies=None, direct_repo_addr_list=None):
        """RepoProxies object

        :param proxies: dict with proto:uri format
        :param direct_repo_addr: list of addr
        :return:
        """
        self.proxies = proxies or {}
        self.direct_repo_addr_list = direct_repo_addr_list or []

    def add_proxy(self, protocol, uri):
        self.proxies[protocol] = uri

    def add_direct_repo_addrs(self, repo_addr_list):
        self.direct_repo_addr_list.extend(repo_addr_list)

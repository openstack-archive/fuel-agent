# Copyright 2016 Mirantis, Inc.
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

import crypt

from fuel_agent.utils import utils


class User(object):
    def __init__(self, name, password, homedir, sudo=None, ssh_keys=None,
                 shell="/bin/bash", hashed_password=None):
        self.name = name
        self.password = password
        self.homedir = homedir
        self.sudo = sudo or []
        self.ssh_keys = ssh_keys or []
        self.shell = shell
        self._hashed_password = hashed_password

    @property
    def hashed_password(self):
        if self.password is None:
            return self._hashed_password

        if self._hashed_password is None:
            self._hashed_password = crypt.crypt(self.password, utils.gensalt())

        return self._hashed_password

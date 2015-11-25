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
import yaml

from fuel_bootstrap import consts
from fuel_bootstrap import errors


class Configuration(object):
    def __init__(self, config_file=None):
        if not config_file:
            config_file = consts.CONFIG_FILE
        if os.path.exists(config_file):
            with open(config_file) as f:
                data = yaml.load(f)
        else:
            raise errors.ConfigFileNotExists(
                "Default config couldn't be found in {0}"
                .format(config_file))
        self._data = data

    def __getattr__(self, name):
        return self._data.get(name)

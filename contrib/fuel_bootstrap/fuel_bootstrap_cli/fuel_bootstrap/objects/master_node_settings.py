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

from fuelclient import client


class MasterNodeSettings(object):
    """Class for working with Fuel master settings"""

    class_api_path = "settings/"

    def __init__(self):
        self.connection = client.APIClient.default_client()

    def update(self, data):
        return self.connection.put_request(
            self.class_api_path, data)

    def get(self):
        return self.connection.get_request(
            self.class_api_path)

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

import mock

from fuel_bootstrap.tests import base


class TestListCommand(base.BaseTest):

    @mock.patch('fuel_bootstrap.utils.bootstrap_image.get_all')
    def test_parser(self, m_get_all):
        m_get_all.return_value = [{
            'uuid': 'fake_uuid',
            'label': 'fake_label',
            'status': 'fake_status',
        }]
        self.app.run(['list'])
        fake_list_result = ("+-----------+------------+-------------+\n"
                            "| uuid      | label      | status      |\n"
                            "+-----------+------------+-------------+\n"
                            "| fake_uuid | fake_label | fake_status |\n"
                            "+-----------+------------+-------------+\n")

        self.assertEqual(fake_list_result, self.app.stdout.getvalue())
        self.assertEqual('', self.app.stderr.getvalue())

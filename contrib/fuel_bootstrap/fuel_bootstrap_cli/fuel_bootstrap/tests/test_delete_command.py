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

UUID = 'fake_uuid'


class TestDeleteCommand(base.BaseTest):

    @mock.patch('fuel_bootstrap.utils.bootstrap_image.delete',
                return_value=UUID)
    def test_parser(self, mock_delete):
        self.app.run(['delete', UUID])
        mock_delete.assert_called_once_with(UUID)
        self.assertEqual("Bootstrap image {0} has been deleted.\n"
                         .format(UUID), self.app.stdout.getvalue())

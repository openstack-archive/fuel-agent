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

import logging
import sys

from cliff import app
from cliff.commandmanager import CommandManager

LOG = logging.getLogger(__name__)


class FuelBootstrap(app.App):
    """Main cliff application class.

    Performs initialization of the command manager and
    configuration of basic engines.

    """

    def initialize_app(self, argv):
        LOG.debug('initialize app')

    def prepare_to_run_command(self, cmd):
        LOG.debug('preparing following command to run: %s',
                  cmd.__class__.__name__)

    def clean_up(self, cmd, result, err):
        LOG.debug('clean up %s', cmd.__class__.__name__)
        if err:
            LOG.debug('got an error: %s', err)


def main(argv=sys.argv[1:]):
    fuel_bootstrap_app = FuelBootstrap(
        description='Command line Fuel bootstrap manager',
        version='0.0.2',
        command_manager=CommandManager('fuel_bootstrap',
                                       convert_underscores=True)
    )
    return fuel_bootstrap_app.run(argv)

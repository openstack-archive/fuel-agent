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

from fuel_bootstrap.commands import base
from fuel_bootstrap.utils import bootstrap_image as bs_image


class ImportCommand(base.BaseCommand):
    """Import already created bootstrap image to the system."""

    def get_parser(self, prog_name):
        parser = super(ImportCommand, self).get_parser(prog_name)
        # shouldn't we check archive file type?
        parser.add_argument(
            'filename',
            type=str,
            metavar='ARCHIVE_FILE',
            help="File name of bootstrap image archive"
        )
        parser.add_argument(
            '--activate',
            help="Activate bootstrap image after import",
            action='store_true'
        )
        return parser

    def take_action(self, parsed_args):
        super(ImportCommand, self).take_action(parsed_args)
        # Cliff handles errors by itself
        image_uuid = bs_image.import_image(parsed_args.filename)
        self.app.stdout.write("Bootstrap image {0} has been imported.\n"
                              .format(image_uuid))
        if parsed_args.activate:
            image_uuid = bs_image.activate(image_uuid)
            self.app.stdout.write("Bootstrap image {0} has been activated\n"
                                  .format(image_uuid))

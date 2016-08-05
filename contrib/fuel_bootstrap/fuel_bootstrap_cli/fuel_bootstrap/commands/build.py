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


class BuildCommand(base.BaseCommand):
    """Build new bootstrap image with specified parameters."""

    def get_parser(self, prog_name):
        parser = super(BuildCommand, self).get_parser(prog_name)
        parser.add_argument(
            '--ubuntu-release',
            type=str,
            help="Choose the Ubuntu release",
        )
        parser.add_argument(
            '--repo',
            dest='repos',
            type=str,
            metavar='REPOSITORY',
            help="Add one more repository. NOTE: The first repo should be"
                 " release repo. REPOSITORY format:"
                 " 'type uri codename [sections][,priority]'.",
            action='append'
        )
        parser.add_argument(
            '--http-proxy',
            type=str,
            metavar='URL',
            help="Pass http-proxy URL."
        )
        parser.add_argument(
            '--https-proxy',
            type=str,
            metavar='URL',
            help="Pass https-proxy URL."
        )
        parser.add_argument(
            '--direct-repo-addr',
            metavar='ADDR',
            help="Use a direct connection to repository(address)"
                 " bypass proxy.",
            action='append'
        )
        parser.add_argument(
            '--script',
            dest='post_script_file',
            type=str,
            metavar='FILE',
            help="The script is executed after installing packages (both"
                 " mandatory and user specified ones) and before creating"
                 " initramfs."
        )
        parser.add_argument(
            '--package',
            dest='packages',
            type=str,
            metavar='PKGNAME',
            help="The option can be given multiple times, all specified"
                 " packages and their dependencies will be installed.",
            action='append'
        )
        parser.add_argument(
            '--label',
            type=str,
            metavar='LABEL',
            help="Custom string, which will be presented in bootstrap"
                 " listing."
        )
        parser.add_argument(
            '--extra-dir',
            dest='extra_dirs',
            type=str,
            metavar='PATH',
            help="Directory that will be injected to the image"
                 " root filesystem. The option can be given multiple times."
                 " **NOTE** Files/packages will be"
                 " injected after installing all packages, but before"
                 " generating system initramfs - thus it's possible to"
                 " adjust initramfs.",
            action='append'
        )
        parser.add_argument(
            '--extend-kopts',
            type=str,
            metavar='OPTS',
            help="Extend default kernel options"
        )
        parser.add_argument(
            '--kernel-flavor',
            type=str,
            help="Defines kernel version."
        )
        parser.add_argument(
            '--root-ssh-authorized-file',
            type=str,
            metavar='FILE',
            help="Copy public ssh key into image - makes it possible"
                 " to login as root into any bootstrap node using the"
                 " key in question."
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            metavar='DIR',
            help="Directory to store built image."
        )
        parser.add_argument(
            '--image-build-dir',
            type=str,
            metavar='DIR',
            help="Which directory should be used for building image."
                 " /tmp/ will be used by default."
        )
        parser.add_argument(
            '--activate',
            help="Activate bootstrap image after build",
            action='store_true'
        )
        parser.add_argument(
            '--no-default-packages',
            help="Do not append default packages",
            action='store_true'
        )
        parser.add_argument(
            '--no-default-direct-repo-addr',
            help="Do not append default direct repo address",
            action='store_true'
        )
        parser.add_argument(
            '--no-default-extra-dirs',
            help="Do not append default extra directories",
            action='store_true'
        )
        parser.add_argument(
            '--no-compress',
            help="Do not compress bootstrap image to tar.gz. Bootstrap"
                 " files will be stored in output dir. NOTE: Not compressed"
                 " images are not supported by fuel-bootstrap.",
            action='store_true'
        )
        parser.add_argument(
            '--load-cert',
            dest='certs',
            metavar='FULL_PATH',
            help="Load CA certificate for https connections. Work as extra"
                 " files",
            action='append'
        )
        parser.add_argument(
            '--root-password',
            type=str,
            help=("Root password for bootstrap image. PasswordAuthentication"
                  " by ssh still rejected by default! This password actual"
                  " only for tty login!"),
        )
        return parser

    def take_action(self, parsed_args):
        super(BuildCommand, self).take_action(parsed_args)
        image_uuid, path = bs_image.make_bootstrap(vars(parsed_args))
        self.app.stdout.write("Bootstrap image {0} has been built: {1}\n"
                              .format(image_uuid, path))
        if parsed_args.activate:
            bs_image.import_image(path)
            bs_image.activate(image_uuid)
            self.app.stdout.write("Bootstrap image {0} has been activated.\n"
                                  .format(image_uuid))

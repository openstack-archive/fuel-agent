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

from cliff import command

from fuel_bootstrap.utils import bootstrap_image as bs_image


class BuildCommand(command.Command):
    """Build new bootstrap image with specified parameters."""

    def get_parser(self, prog_name):
        parser = super(BuildCommand, self).get_parser(prog_name)
        parser.add_argument(
            '--ubuntu-release',
            type=str,
            help="Choose the Ubuntu release (currently supports"
                 " only trusty).",
        )
        parser.add_argument(
            '--ubuntu-repo',
            type=str,
            metavar='REPOSITORY',
            help="Use the specified Ubuntu repository. Format"
                 " 'uri codename'.",
        )
        parser.add_argument(
            '--mos-repo',
            type=str,
            metavar='REPOSITORY',
            help="Add link to repository with fuel* packages. That"
                 " should either http://mirror.fuel-infra.org/mos-repos"
                 " or its mirror. Format 'uri codename'.",
        )
        parser.add_argument(
            '--repo',
            dest='repos',
            type=str,
            metavar='REPOSITORY',
            help="Add one more repository. format 'type uri"
                 " codename [sections][,priority]'.",
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
            '--include-kernel-module',
            help="Make sure the given modules are included into initramfs"
                 " image. (by adding module into /etc/initramfs-tools/"
                 "modules) **NOTE** If the module in question is not"
                 " shipped with the kernel itself please add the package"
                 " providing it (see the `--packege` option). Keep in mind"
                 " that initramfs image should be kept as small as"
                 " possible. This option is intended to include uncommon"
                 " network interface cards' drivers so the initramfs can"
                 " fetch the root filesystem image via the network."
        )
        parser.add_argument(
            '--blacklist-kernel-module',
            help="Make sure the given modules never get loaded"
                 " automatically. **NOTE** Direct injection of files into"
                 " the image is not recommended, and a proper way to"
                 " customize an image is adding (custom) packages."
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
            '--extra-file',
            dest='extra_files',
            type=str,
            metavar='PATH',
            help="Directory that will be injected to the image"
                 " root filesystem. **NOTE** Files/packages will be"
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
            help="Defines kernel version. 'linux-image-generic-lts-trusty'"
                 " will be used by default.",
            default='linux-image-generic-lts-trusty'
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
            help="Which directory should contain built image. /tmp/"
                 " is used by default.",
            default="/tmp/"
        )
        parser.add_argument(
            '--image-build-dir',
            type=str,
            metavar='DIR',
            help="Which directory should be used for building image."
                 " /tmp/ will be used by default.",
            default="/tmp/"
        )
        return parser

    def take_action(self, parsed_args):
        bs_image.make_bootstrap(parsed_args)

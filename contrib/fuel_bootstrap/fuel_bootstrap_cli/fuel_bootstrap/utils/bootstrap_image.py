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
import os
import re
import shutil
import tarfile
import tempfile
import yaml

from fuel_agent import manager
from fuel_agent.utils import utils
from oslo_config import cfg

from fuel_bootstrap import consts
from fuel_bootstrap import errors
from fuel_bootstrap import settings
from fuel_bootstrap.utils import data as data_util
from fuel_bootstrap.utils import notifier

CONF = settings.CONF
LOG = logging.getLogger(__name__)
ACTIVE = 'active'


def get_all():
    """Return info about all valid bootstrap images

    :return: array of dict
    """
    # TODO(asvechnikov): need to change of determining active bootstrap
    #                    cobbler profile must be used
    data = []
    LOG.debug("Searching images in %s", CONF.bootstrap_images_dir)
    for name in os.listdir(CONF.bootstrap_images_dir):
        if not os.path.isdir(os.path.join(CONF.bootstrap_images_dir, name)):
            continue
        try:
            data.append(parse(name))
        except errors.IncorrectImage as e:
            LOG.debug("Image [%s] is skipped due to %s", name, e)
    return data


def _cobbler_profile():
    """Parse current active profile from cobbler system

    :return: string
    """

    stdout, _ = utils.execute('cobbler', 'system', 'report',
                              '--name', 'default')
    regex = r"(?P<label>Profile)\s*:\s*(?P<profile>[^\s]+)"
    return re.search(regex, stdout).group('profile')


def parse(image_uuid):
    LOG.debug("Trying to parse [%s] image", image_uuid)
    dir_path = full_path(image_uuid)
    if os.path.islink(dir_path) or not os.path.isdir(dir_path):
        raise errors.IncorrectImage("There are no such image [{0}]."
                                    .format(image_uuid))

    metafile = os.path.join(dir_path, consts.METADATA_FILE)
    if not os.path.exists(metafile):
        raise errors.IncorrectImage("Image [{0}] doesn't contain metadata "
                                    "file.".format(image_uuid))

    with open(metafile) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise errors.IncorrectImage("Couldn't parse metadata file for"
                                        " image [{0}] due to {1}"
                                        .format(image_uuid, e))
    if data.get('uuid') != os.path.basename(dir_path):
        raise errors.IncorrectImage("UUID from metadata file [{0}] doesn't"
                                    " equal directory name [{1}]"
                                    .format(data.get('uuid'), image_uuid))

    data['status'] = ACTIVE if is_active(data['uuid']) else ''
    data.setdefault('label', '')
    return data


def delete(image_uuid):
    dir_path = full_path(image_uuid)
    image = parse(image_uuid)
    if image['status'] == ACTIVE:
        raise errors.ActiveImageException("Image [{0}] is active and can't be"
                                          " deleted.".format(image_uuid))

    shutil.rmtree(dir_path)
    return image_uuid


def is_active(image_uuid):
    return full_path(image_uuid) == os.path.realpath(
        CONF.active_bootstrap_symlink)


def full_path(image_uuid):
    if not os.path.isabs(image_uuid):
        return os.path.join(CONF.bootstrap_images_dir, image_uuid)
    return image_uuid


def import_image(arch_path):
    extract_dir = tempfile.mkdtemp()
    extract_to_dir(arch_path, extract_dir)

    metafile = os.path.join(extract_dir, consts.METADATA_FILE)

    with open(metafile) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise errors.IncorrectImage("Couldn't parse metadata file"
                                        " due to {0}".format(e))

    image_uuid = data['uuid']
    dir_path = full_path(image_uuid)

    if os.path.exists(dir_path):
        raise errors.ImageAlreadyExists("Image [{0}] already exists."
                                        .format(image_uuid))

    shutil.move(extract_dir, dir_path)
    os.chmod(dir_path, 0o755)
    for root, dirs, files in os.walk(dir_path):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o755)

    return image_uuid


def extract_to_dir(arch_path, extract_path):
    LOG.info("Try extract %s to %s", arch_path, extract_path)
    tarfile.open(arch_path, 'r').extractall(extract_path)


def make_bootstrap(data):
    bootdata_builder = data_util.BootstrapDataBuilder(data)
    bootdata = bootdata_builder.build()

    LOG.info("Try to build image with data:\n%s", yaml.safe_dump(bootdata))

    opts = ['--data_driver', 'bootstrap_build_image']
    if data.get('image_build_dir'):
        opts.extend(['--image_build_dir', data['image_build_dir']])

    OSLO_CONF = cfg.CONF
    OSLO_CONF(opts, project='fuel-agent')
    mngr = manager.Manager(bootdata)
    LOG.info("Build process is in progress. Usually it takes 15-20 minutes."
             " It depends on your internet connection and hardware"
             " performance.")
    mngr.do_mkbootstrap()

    return bootdata['bootstrap']['uuid'], bootdata['output']


def _update_astute_yaml(flavor=None):
    config = consts.ASTUTE_CONFIG_FILE
    LOG.debug("Switching in %s BOOTSTRAP/flavor to :%s",
              config, flavor)
    try:
        with open(config, 'r') as f:
            data = yaml.safe_load(f)
        data['BOOTSTRAP']['flavor'] = flavor
        with open(config, 'wt') as f:
            yaml.safe_dump(data, stream=f, encoding='utf-8',
                           default_flow_style=False,
                           default_style='"')
    except IOError:
        LOG.error("Config file %s has not been processed successfully", config)
        raise
    except (KeyError, TypeError):
        LOG.error("Seems config file %s is empty or doesn't contain BOOTSTRAP"
                  " section", config)
        raise


def _run_puppet(manifest=None):
    """Run puppet apply

    :param manifest:
    :return:
    """
    LOG.debug('Trying apply manifest: %s', manifest)
    utils.execute('puppet', 'apply', '--detailed-exitcodes',
                  '-dv', manifest, logged=True,
                  check_exit_code=[0, 2], attempts=2)


def _activate_flavor(flavor=None):
    """Switch between cobbler distro profiles, in case dockerized system

    Unfortunately, we don't support switching between profiles "on fly",
    so to perform this we need:
    1) Update asute.yaml - which used by puppet to determine options
    2) Re-run puppet for cobbler(to perform default system update, regarding
       new profile)
    3) Re-run puppet for astute

    :param flavor: Switch between cobbler profile
    :return:
    """
    flavor = flavor.lower()
    if flavor not in consts.DISTROS:
        raise errors.WrongCobblerProfile(
            'Wrong cobbler profile passed: {0} \n '
            'possible profiles: {1}'.format(flavor,
                                            list(consts.DISTROS.keys())))
    _update_astute_yaml(consts.DISTROS[flavor]['astute_flavor'])
    _run_puppet(consts.COBBLER_MANIFEST)
    _run_puppet(consts.ASTUTE_MANIFEST)
    # restart astuted to be sure that it catches new profile
    LOG.debug('Reloading astuted')
    utils.execute('service', 'astute', 'restart')


def _make_symlink(symlink, dir_path):
    if os.path.lexists(symlink):
        os.unlink(symlink)
        LOG.debug("Symlink %s was deleted", symlink)

    os.symlink(dir_path, symlink)
    LOG.debug("Symlink %s to %s directory has been created", symlink, dir_path)


@notifier.notify_webui_on_fail
def _activate_image(image_uuid):
    symlink = CONF.active_bootstrap_symlink
    dir_path = full_path(image_uuid)

    _make_symlink(symlink, dir_path)

    # FIXME: Add pre-activate verify
    flavor = 'ubuntu'
    _activate_flavor(flavor)

    notifier.notify_webui("")

    return image_uuid


def activate(image_uuid):
    # need to verify image_uuid
    # TODO(asvechnikov): add check for already active image_uuid
    #                    after cobbler will be used for is_active
    parse(image_uuid)

    return _activate_image(image_uuid)

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
import shutil
import tarfile
import tempfile
import yaml

from fuel_agent import manager
from fuel_agent.utils import utils
from oslo_config import cfg

from fuel_bootstrap import consts
from fuel_bootstrap import errors
from fuel_bootstrap.objects import master_node_settings
from fuel_bootstrap import settings
from fuel_bootstrap.utils import data as data_util

CONF = settings.Configuration()
LOG = logging.getLogger(__name__)
ACTIVE = 'active'


def get_all():
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


def parse(image_uuid):
    LOG.debug("Trying to parse [%s] image", image_uuid)
    dir_path = full_path(image_uuid)
    if os.path.islink(dir_path) or not os.path.isdir(dir_path):
        raise errors.IncorrectImage("There are no such image [{0}]."
                                    .format(image_uuid))

    metafile = os.path.join(dir_path, consts.METADATA_FILE)
    if not os.path.exists(metafile):
        raise errors.IncorrectImage("Image [{0}] doen's contain metadata file."
                                    .format(image_uuid))

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


def make_bootstrap(data=None):
    if not data:
        data = {}
    bootdata_builder = data_util.BootstrapDataBuilder(data)
    bootdata = bootdata_builder.build()

    LOG.info("Try to build image with data:\n%s", yaml.safe_dump(bootdata))

    OSLO_CONF = cfg.CONF
    OSLO_CONF(['--data_driver', 'bootstrap_build_image'], project='fuel-agent')
    mngr = manager.Manager(bootdata)
    LOG.info("Build process is in progress. Usually it takes 15-20 minutes."
             " It depends on your internet connection and hardware"
             " performance.")
    mngr.do_mkbootstrap()

    return bootdata['bootstrap']['uuid'], bootdata['output']


def activate(image_uuid=""):
    is_centos = image_uuid.lower() == 'centos'
    symlink = CONF.active_bootstrap_symlink

    if os.path.lexists(symlink):
        os.unlink(symlink)
        LOG.debug("Symlink %s was deleted", symlink)

    if not is_centos:
        parse(image_uuid)
        dir_path = full_path(image_uuid)
        os.symlink(dir_path, symlink)
        LOG.debug("Symlink %s to %s directory has been created",
                  symlink, dir_path)
    else:
        LOG.warning("WARNING: switching to depracated centos-bootstrap")

    # FIXME: Do normal activation when it become clear how to do it
    flavor = 'centos' if is_centos else 'ubuntu'
    utils.execute('fuel-bootstrap-image-set', flavor)

    return image_uuid


def call_wrapped_method(name, notify_webui, **kwargs):
    wrapped_methods = {
        'build': make_bootstrap,
        'activate': activate
    }
    failed = False
    try:
        return wrapped_methods[name](**kwargs)
    except Exception:
        failed = True
        raise
    finally:
        if notify_webui:
            notify_webui_about_results(failed, consts.ERROR_MSG)


def notify_webui_about_results(failed, error_message):
    mn_settings = master_node_settings.MasterNodeSettings()
    settings = mn_settings.get()
    settings['settings'].setdefault('bootstrap', {}).setdefault('error', {})
    if not failed:
        error_message = ""
    settings['settings']['bootstrap']['error']['value'] = error_message
    mn_settings.update(settings)

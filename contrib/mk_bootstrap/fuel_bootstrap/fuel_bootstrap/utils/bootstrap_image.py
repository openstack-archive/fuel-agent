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

from fuel_bootstrap import consts
from fuel_bootstrap import errors


LOG = logging.getLogger(__name__)
ACTIVE = 'active'


def get_all():
    data = []
    LOG.debug("Searching images in %s", consts.BOOTSTRAP_IMAGES_DIR)
    for name in os.listdir(consts.BOOTSTRAP_IMAGES_DIR):
        if not os.path.isdir(os.path.join(consts.BOOTSTRAP_IMAGES_DIR, name)):
            continue
        try:
            data.append(parse(name))
        except errors.IncorrectImage as e:
            LOG.debug("Image [%s] is skipped due to %s", name, e)
    return data


def parse(image_id):
    LOG.debug("Trying to parse [%s] image", image_id)
    dir_path = full_path(image_id)
    if os.path.islink(dir_path) or not os.path.isdir(dir_path):
        raise errors.IncorrectImage("There are no such image [{0}]."
                                    .format(image_id))

    metafile = os.path.join(dir_path, consts.METADATA_FILE)
    if not os.path.exists(metafile):
        raise errors.IncorrectImage("Image [{0}] doen's contain metadata file."
                                    .format(image_id))

    with open(metafile) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise errors.IncorrectImage("Couldn't parse metadata file for"
                                        " image [{0}] due to {1}"
                                        .format(image_id, e))
    if data.get('uuid') != os.path.basename(dir_path):
        raise errors.IncorrectImage("UUID from metadata file [{0}] doesn't"
                                    " equal directory name [{1}]"
                                    .format(data.get('uuid'), image_id))

    data['status'] = ACTIVE if is_active(data['uuid']) else ''
    return data


def delete(image_id):
    dir_path = full_path(image_id)
    image = parse(image_id)
    if image['status'] == ACTIVE:
        raise errors.ActiveImageException("Image [{0}] is active and can't be"
                                          " deleted.".format(image_id))

    shutil.rmtree(dir_path)
    return image_id


def is_active(image_id):
    return full_path(image_id) == os.path.realpath(consts.SYMLINK)


def full_path(image_id):
    if not os.path.isabs(image_id):
        return os.path.join(consts.BOOTSTRAP_IMAGES_DIR, image_id)
    return image_id


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

    image_id = data['uuid']
    dir_path = full_path(image_id)

    if os.path.exists(dir_path):
        raise errors.ImageAlreadyExists("Image [{0}] already exists."
                                        .format(image_id))

    shutil.move(extract_dir, dir_path)


def extract_to_dir(arch_path, extract_path):
    LOG.info("Try extract %s to %s", arch_path, extract_path)
    tarfile.open(arch_path, 'r').extractall(extract_path)

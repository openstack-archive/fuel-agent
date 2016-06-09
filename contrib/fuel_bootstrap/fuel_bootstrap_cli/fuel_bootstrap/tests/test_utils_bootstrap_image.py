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
import os
import unittest

import fuel_agent
import mock
from oslo_config import cfg

from fuel_bootstrap import consts
from fuel_bootstrap import errors
from fuel_bootstrap.utils import bootstrap_image as bs_image
from fuel_bootstrap.utils import data
from fuel_bootstrap.utils import notifier


# FAKE_OS is list of tuples which describes fake directories for testing.
# Each tuple has the following structure:
#     (root, list_of_directories, list_of_files)
FAKE_OS = [
    (
        '/test',
        ['/test/image_1', '/test/image_2', '/test/link_active_bootstrap'],
        ['/test/test_file']
    ),
    ('/test/image_1', [], ['/test/image_1/metadata.yaml']),
    ('/test/image_2', [], [])
]

DATA = [{'uuid': 'image_1', 'status': 'active'}, {'uuid': 'image_2'}]

IMAGES_DIR = '/test'

BOOTSTRAP_SYMLINK = '/test/link_active_bootstrap'


def _is_link(dir_path):
    return dir_path.startswith('link')


def _list_dir(bootstrap_images_dir):
    result = []
    for item in FAKE_OS:
        if item[0] == bootstrap_images_dir:
            result.extend(item[1])
            result.extend(item[2])
    return result


def _is_dir(dir_path):
    for item in FAKE_OS:
        if item[0] == dir_path:
            return True
    return False


def _exists(dir_path):
    for root, dirs, files in FAKE_OS:
        if dir_path in dirs or dir_path in files:
            return True


class BootstrapImageTestCase(unittest.TestCase):
    def setUp(self):
        super(BootstrapImageTestCase, self).setUp()
        self.conf_patcher = mock.patch.object(bs_image, 'CONF')
        self.conf_mock = self.conf_patcher.start()

        self.conf_mock.bootstrap_images_dir = IMAGES_DIR
        self.conf_mock.active_bootstrap_symlink = BOOTSTRAP_SYMLINK

        self.open_patcher = mock.patch('fuel_bootstrap.utils.bootstrap_image.'
                                       'open', create=True,
                                       new_callable=mock.mock_open)
        self.open_mock = self.open_patcher.start()

        self.yaml_patcher = mock.patch('yaml.safe_load')
        self.yaml_mock = self.yaml_patcher.start()

        self.dir_patcher = mock.patch('os.listdir')
        self.dir_mock = self.dir_patcher.start()
        self.dir_mock.side_effect = _list_dir

        self.is_dir_patcher = mock.patch('os.path.isdir')
        self.is_dir_mock = self.is_dir_patcher.start()
        self.is_dir_mock.side_effect = _is_dir

        self.is_link_patcher = mock.patch('os.path.islink')
        self.is_link_mock = self.is_link_patcher.start()
        self.is_link_mock.side_effect = _is_link

        self.exists_patcher = mock.patch('os.path.exists')
        self.exists_mock = self.exists_patcher.start()
        self.exists_mock.side_effect = _exists

        self.walk_patcher = mock.patch('os.walk')
        self.walk_mock = self.walk_patcher.start()
        self.walk_mock.return_value = [('/test/image_3',
                                        ['directory'], ['file'])]

    def tearDown(self):
        mock.patch.stopall()

    @mock.patch.object(bs_image, 'parse', side_effect=DATA)
    def test_get_all(self, parse_mock):
        result = bs_image.get_all()
        self.assertEqual(DATA, result)
        self.assertEqual(2, parse_mock.call_count)
        parse_mock.assert_has_calls([mock.call('/test/image_1'),
                                     mock.call('/test/image_2')])

    @mock.patch('os.path.islink', return_value=True)
    def test_parse_link(self, islink_mock):
        image_uuid = '/test/link_active_bootstrap'
        error_msg = "There are no such image \[{0}].".format(image_uuid)
        with self.assertRaisesRegexp(errors.IncorrectImage, error_msg):
            bs_image.parse(image_uuid)

    @mock.patch('os.path.isdir', return_value=False)
    def test_parse_not_dir(self, isdir_mock):
        image_uuid = '/test/test_file'
        error_msg = "There are no such image \[{0}].".format(image_uuid)
        with self.assertRaisesRegexp(errors.IncorrectImage, error_msg):
            bs_image.parse(image_uuid)

    def test_parse_no_metadata(self):
        image_uuid = '/test/image_2'
        error_msg = ("Image \[{0}] doesn't contain metadata file."
                     .format(image_uuid))
        with self.assertRaisesRegexp(errors.IncorrectImage, error_msg):
            bs_image.parse(image_uuid)

    def test_parse_wrong_dir_name(self):
        image_uuid = '/test/image_1'
        self.yaml_mock.return_value = {'uuid': 'image_2'}
        error_msg = ("UUID from metadata file \[{0}] doesn't equal"
                     " directory name \[{1}]".format('image_2', image_uuid))
        with self.assertRaisesRegexp(errors.IncorrectImage, error_msg):
            bs_image.parse(image_uuid)

    @mock.patch.object(bs_image, 'is_active')
    def test_parse_correct_image(self, active_mock):
        active_mock.return_value = False
        image_uuid = '/test/image_1'
        self.yaml_mock.return_value = {'uuid': 'image_1'}
        expected_data = {
            'uuid': 'image_1',
            'label': '',
            'status': '',
        }
        data = bs_image.parse(image_uuid)
        self.assertEqual(expected_data, data)

    @mock.patch.object(bs_image, 'is_active')
    def test_parse_active_image(self, active_mock):
        active_mock.return_value = True
        image_uuid = '/test/image_1'
        self.yaml_mock.return_value = {'uuid': 'image_1'}
        expected_data = {
            'uuid': 'image_1',
            'label': '',
            'status': 'active',
        }
        data = bs_image.parse(image_uuid)
        self.assertEqual(expected_data, data)

    @mock.patch.object(bs_image, 'parse')
    def test_delete_active_image(self, parse_mock):
        parse_mock.return_value = DATA[0]
        image_uuid = '/test/image_1'
        error_msg = ("Image \[{0}] is active and can't be deleted."
                     .format(image_uuid))

        with self.assertRaisesRegexp(errors.ActiveImageException, error_msg):
            bs_image.delete(image_uuid)

    @mock.patch.object(bs_image, 'parse')
    @mock.patch('shutil.rmtree')
    def test_delete(self, shutil_mock, parse_mock):
        image_uuid = '/test/image_2'
        self.assertEqual(image_uuid, bs_image.delete(image_uuid))
        parse_mock.assert_called_once_with('/test/image_2')
        shutil_mock.assert_called_once_with(image_uuid)

    @mock.patch('os.path.realpath', return_value='/test/image_1')
    def test_is_active(self, realpath_mock):
        image_uuid = '/test/image_1'
        self.assertTrue(bs_image.is_active(image_uuid))

    def test_full_path_not_full(self):
        image_uuid = 'image_1'
        result = bs_image.full_path(image_uuid)
        self.assertEqual(os.path.join(IMAGES_DIR, image_uuid), result)

    def test_full_path_full(self):
        image_uuid = '/test/image_1'
        result = bs_image.full_path(image_uuid)
        self.assertEqual(image_uuid, result)

    @mock.patch('tempfile.mkdtemp')
    @mock.patch('fuel_bootstrap.utils.bootstrap_image.extract_to_dir')
    def test_import_exists_image(self, extract_mock, tempfile_mock):
        self.yaml_mock.return_value = DATA[0]
        image_uuid = DATA[0].get('uuid')
        error_msg = ("Image \[{0}] already exists.".format(image_uuid))
        with self.assertRaisesRegexp(errors.ImageAlreadyExists, error_msg):
            bs_image.import_image('/path')

    @mock.patch('os.chmod')
    @mock.patch('shutil.move')
    @mock.patch('tempfile.mkdtemp', return_value='/tmp/test')
    @mock.patch('fuel_bootstrap.utils.bootstrap_image.extract_to_dir')
    def test_import_image(self, extract_mock, tempfile_mock, shutil_mock,
                          chmod_mock):
        arch_path = '/path'
        extract_dir = '/tmp/test'
        dir_path = '/test/image_3'
        self.yaml_mock.return_value = {'uuid': dir_path}
        self.assertEqual(bs_image.import_image('/path'), dir_path)
        tempfile_mock.assert_called_once_with()
        extract_mock.assert_called_once_with(arch_path, extract_dir)
        shutil_mock.assert_called_once_with(extract_dir, dir_path)
        chmod_mock.assert_has_calls([
            mock.call(dir_path, 0o755),
            mock.call(os.path.join(dir_path, 'directory'), 0o755),
            mock.call(os.path.join(dir_path, 'file'), 0o755)])

    @mock.patch('tarfile.open')
    def test_extract_to_dir(self, tarfile_mock):
        bs_image.extract_to_dir('arch_path', 'extract_path')
        tarfile_mock.assert_called_once_with('arch_path', 'r')
        tarfile_mock().extractall.assert_called_once_with('extract_path')

    @mock.patch.object(cfg, 'CONF')
    @mock.patch.object(fuel_agent.manager, 'Manager')
    @mock.patch.object(data, 'BootstrapDataBuilder')
    def test_make_bootstrap(self, bdb_mock, manager_mock, conf_mock):
        data = {}
        boot_data = {'bootstrap': {'uuid': 'image_1'},
                     'output': '/image/path'}
        opts = ['--data_driver', 'bootstrap_build_image']
        bdb_mock(data).build.return_value = boot_data

        self.assertEqual(('image_1', '/image/path'),
                         bs_image.make_bootstrap(data))
        conf_mock.assert_called_once_with(opts, project='fuel-agent')
        manager_mock(boot_data).do_mkbootstrap.assert_called_once_with()

    @mock.patch.object(cfg, 'CONF')
    @mock.patch.object(fuel_agent.manager, 'Manager')
    @mock.patch.object(data, 'BootstrapDataBuilder')
    def test_make_bootstrap_image_build_dir(self,
                                            bdb_mock,
                                            manager_mock,
                                            conf_mock):
        data = {'image_build_dir': '/image/build_dir'}
        boot_data = {'bootstrap': {'uuid': 'image_1'},
                     'output': '/image/path'}
        opts = ['--data_driver', 'bootstrap_build_image',
                '--image_build_dir', data['image_build_dir']]
        bdb_mock(data).build.return_value = boot_data

        self.assertEqual(('image_1', '/image/path'),
                         bs_image.make_bootstrap(data))
        self.assertEqual(2, bdb_mock.call_count)
        conf_mock.assert_called_once_with(opts, project='fuel-agent')
        manager_mock(boot_data).do_mkbootstrap.assert_called_once_with()

    def test_update_astute_yaml_key_error(self):
        self.yaml_mock.return_value = {}
        with self.assertRaises(KeyError):
            bs_image._update_astute_yaml()

    def test_update_astute_yaml_type_error(self):
        self.yaml_mock.return_value = []
        with self.assertRaises(TypeError):
            bs_image._update_astute_yaml()

    @mock.patch('fuel_agent.utils.utils.execute')
    def test_run_puppet_no_manifest(self, execute_mock):
        bs_image._run_puppet()
        execute_mock.assert_called_once_with('puppet', 'apply',
                                             '--detailed-exitcodes',
                                             '-dv', None, logged=True,
                                             check_exit_code=[0, 2],
                                             attempts=2)

    def test_activate_flavor_not_in_distros(self):
        flavor = 'not_ubuntu'
        error_msg = ('Wrong cobbler profile passed: {0} \n '
                     'possible profiles: \{1}'.
                     format(flavor, list(consts.DISTROS.keys())))
        with self.assertRaisesRegexp(errors.WrongCobblerProfile, error_msg):
            bs_image._activate_flavor(flavor)

    @mock.patch.object(bs_image, '_update_astute_yaml')
    @mock.patch.object(bs_image, '_run_puppet')
    @mock.patch.object(fuel_agent.utils.utils, 'execute')
    def test_activate_flavor(self,
                             execute_mock,
                             run_puppet_mock,
                             update_astute_yaml_mock):
        flavor = 'ubuntu'
        bs_image._activate_flavor(flavor)
        update_astute_yaml_mock.assert_called_once_with(
            consts.DISTROS[flavor]['astute_flavor'])
        run_puppet_mock.assert_any_call(consts.COBBLER_MANIFEST)
        run_puppet_mock.assert_any_call(consts.ASTUTE_MANIFEST)
        self.assertEqual(2, run_puppet_mock.call_count)
        execute_mock.assert_called_once_with('service', 'astute', 'restart')

    @mock.patch('os.path.lexists', return_value=False)
    @mock.patch('os.unlink')
    @mock.patch('os.symlink')
    def tests_make_symlink(self, symlink_mock, unlink_mock, lexist_mock):
        dir_path = '/test/test_image_uuid'
        symlink = '/test/active_bootstrap'
        bs_image._make_symlink(symlink, dir_path)
        lexist_mock.assert_called_once_with(symlink)
        unlink_mock.assert_not_called()
        symlink_mock.assert_called_once_with(dir_path, symlink)

    @mock.patch('os.path.lexists', return_value=True)
    @mock.patch('os.unlink')
    @mock.patch('os.symlink')
    def tests_make_deteted_symlink(self, symlink_mock, unlink_mock,
                                   lexist_mock):
        dir_path = '/test/test_image_uuid'
        symlink = '/test/active_bootstrap'
        bs_image._make_symlink(symlink, dir_path)
        lexist_mock.assert_called_once_with(symlink)
        unlink_mock.assert_called_once_with(symlink)
        symlink_mock.assert_called_once_with(dir_path, symlink)

    @mock.patch.object(bs_image, '_activate_flavor')
    @mock.patch.object(notifier, 'notify_webui')
    @mock.patch.object(bs_image, '_make_symlink')
    def test_activate_image_symlink_deleted(self,
                                            make_symlink_mock,
                                            notify_mock,
                                            activate_flavor_mock):
        image_uuid = '/test/test_image_uuid'
        symlink = '/test/active_bootstrap'
        self.conf_mock.active_bootstrap_symlink = symlink
        self.assertEqual(image_uuid, bs_image._activate_image(image_uuid))
        make_symlink_mock.assert_called_once_with(symlink, image_uuid)
        activate_flavor_mock.assert_called_once_with('ubuntu')
        notify_mock.assert_called_once_with("")

    @mock.patch.object(bs_image, 'parse')
    @mock.patch.object(bs_image, '_activate_image')
    def test_activate(self, activate_mock, parse_mock):
        image_uuid = '/test/test_image_uuid'
        activate_mock.return_value = image_uuid
        self.assertEqual(image_uuid, bs_image.activate(image_uuid))
        parse_mock.assert_called_once_with(image_uuid)
        activate_mock.assert_called_once_with(image_uuid)

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

import io

import pytest

from fuel_bootstrap import main


class SafeBootstrapApp(main.FuelBootstrap):
    def build_option_parser(self, description, version, argparse_kwargs=None):
        parser = super(SafeBootstrapApp, self).build_option_parser(
            description, version, argparse_kwargs)
        parser.set_defaults(debug=True)
        return parser

    def get_fuzzy_matches(self, cmd):
        # Turn off guessing, we need exact failures in tests
        return []

    def run(self, argv):
        try:
            exit_code = super(SafeBootstrapApp, self).run(argv)
        except SystemExit as e:
            exit_code = e.code
        assert exit_code == 0


class SafeStringIO(io.StringIO):

    def write(self, s):
        try:
            s = unicode(s)
        except NameError:
            pass
        super(SafeStringIO, self).write(s)


@pytest.fixture
def bootstrap_app(request):
    request.cls.app = SafeBootstrapApp(
        stdin=SafeStringIO(),
        stdout=SafeStringIO(),
        stderr=SafeStringIO()
    )

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

from fuel_bootstrap.objects import master_node_settings
from requests import exceptions

LOG = logging.getLogger(__name__)


def notify_webui_on_fail(function):
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            notify_webui("Last bootstrap image activation was failed."
                         " It's possible that nodes will not discovered"
                         " after reboot.")
            raise
    return wrapper


def notify_webui(error_message):
    try:
        mn_settings = master_node_settings.MasterNodeSettings()
        settings = mn_settings.get()
        settings['settings'].setdefault('bootstrap', {}).setdefault(
            'error', {})['value'] = error_message
        mn_settings.update(settings)
    except exceptions.ConnectionError as exc:
        LOG.warning("Can't send notification '%s' to WebUI due to %s",
                    error_message, exc)
    except KeyError:
        LOG.warning("WebUI settings doesn't contain 'settings' section")

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

import json
import sys
import time

import requests

from fuel_agent.utils import utils

_GET_ADDR_MAX_ITERATION = 50
_POST_CALLBACK_MAX_ITERATION = 50
_RETRY_INTERVAL = 5


def _process_error(message):
    sys.stderr.write(message)
    sys.stderr.write('\n')
    sys.exit(1)


def main():
    """Script informs Ironic that bootstrap loading is done.

    There are three mandatory parameters in kernel command line.
    Ironic prepares these two:
    'api-url' - URL of Ironic API service,
    'deployment_id' - UUID of the node in Ironic.
    Passed from PXE boot loader:
    'BOOTIF' - MAC address of the boot interface,
    http://www.syslinux.org/wiki/index.php/SYSLINUX#APPEND_-
    Example: api_url=http://192.168.122.184:6385
    deployment_id=eeeeeeee-dddd-cccc-bbbb-aaaaaaaaaaaa
    BOOTIF=01-88-99-aa-bb-cc-dd
    """
    kernel_params = utils.parse_kernel_cmdline()
    api_url = kernel_params.get('api-url')
    deployment_id = kernel_params.get('deployment_id')
    if api_url is None or deployment_id is None:
        _process_error('Mandatory parameter ("api-url" or "deployment_id") is '
                       'missing.')

    bootif = kernel_params.get('BOOTIF')
    if bootif is None:
        _process_error('Cannot define boot interface, "BOOTIF" parameter is '
                       'missing.')

    # The leading `01-' denotes the device type (Ethernet) and is not a part of
    # the MAC address
    boot_mac = bootif[3:].replace('-', ':')
    for n in range(_GET_ADDR_MAX_ITERATION):
        boot_ip = utils.get_interface_ip(boot_mac)
        if boot_ip is not None:
            break
        time.sleep(_RETRY_INTERVAL)
    else:
        _process_error('Cannot find IP address of boot interface.')

    # NOTE(pas-ha) supporting only Ironic API >= 1.22 !!!
    headers = {'Content-Type': 'application/json',
               'Accept': 'application/json',
               'X-OpenStack-Ironic-API-Version': '1.22'}
    data = {"callback_url": "ssh://" + boot_ip}
    heartbeat = '{api_url}/v1/heartbeat/{uuid}'.format(api_url=api_url,
                                                       uuid=deployment_id)

    for attempt in range(_POST_CALLBACK_MAX_ITERATION):
        try:
            resp = requests.post(heartbeat, data=json.dumps(data),
                                 headers=headers)
        except Exception as e:
            error = str(e)
        else:
            if resp.status_code != 202:
                error = ('Wrong status code %d returned from Ironic API' %
                         resp.status_code)
            else:
                break
        time.sleep(_RETRY_INTERVAL)
    else:
        # executed only when whole for block was executed w/o breaks
        _process_error(error)

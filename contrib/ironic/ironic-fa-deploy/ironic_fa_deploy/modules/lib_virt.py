# Copyright (c) 2015 Mirantis, Inc.
# All Rights Reserved.
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

"""
Ironic Libvirt power manager and management interface.

Provides basic power control and management of virtual machines
via Libvirt API.

For use in dev and test environments.

Currently supported environments are:
    Virtual Box
    Virsh
    VMware WS/ESX/Player
    Parallels
    XenServer
    OpenVZ
    Microsoft Hyper-V
    Virtuozzo

Currently supported transports are:
    unix (open auth)
    tcp (SASL auth)
    tls (SASL auth)
    ssh (SSH Key auth)

"""

import os
import xml.etree.ElementTree as ET

import libvirt
from oslo_config import cfg
from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers import utils as driver_utils

from ironic_fa_deploy.common import exception as f_exc


CONF = cfg.CONF

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'libvirt_uri': _("libvirt URI. Example: qemu+unix:///system . "
                     "Required."),
}
OTHER_PROPERTIES = {
    'sasl_username': _("username to authenticate as. Optional."),
    'sasl_password': _("password to use for SASL authentication. Optional."),
    'ssh_key_filename': _("filename of optional private key "
                          "for authentication. Optional.")
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OTHER_PROPERTIES)


_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'hd',
    boot_devices.PXE: 'network',
    boot_devices.CDROM: 'cdrom',
}


def _normalize_mac(mac):
    return mac.replace('-', '').replace(':', '').lower()


def _get_libvirt_connection(driver_info):
    """Get the libvirt connection.

    :param driver_info: driver info
    :returns: the active libvirt connection
    :raises: LibvirtError if failed to connect to the Libvirt uri.
    """

    uri = driver_info['libvirt_uri']
    sasl_username = driver_info.get('sasl_username')
    sasl_password = driver_info.get('sasl_password')
    ssh_key_filename = driver_info.get('ssh_key_filename')

    try:
        if sasl_username and sasl_password:
            def request_cred(credentials, user_data):
                for credential in credentials:
                    if credential[0] == libvirt.VIR_CRED_AUTHNAME:
                        credential[4] = sasl_username
                    elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
                        credential[4] = sasl_password
                return 0
            auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE],
                    request_cred, None]
            conn = libvirt.openAuth(uri, auth, 0)
        elif ssh_key_filename:
            uri += "?keyfile=%s&no_verify=1" % ssh_key_filename
            conn = libvirt.open(uri)
        else:
            conn = libvirt.open(uri)
    except libvirt.libvirtError as e:
        raise f_exc.LibvirtError(err=e)

    if conn is None:
        raise f_exc.LibvirtError(
            err=_("Failed to open connection to %s") % uri)
    return conn


def _get_domain_by_macs(task):
    """Get the domain the host uses to reference the node.

    :param task: a TaskManager instance containing the node to act on
    :returns: the libvirt domain object.
    :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
    :raises: InvalidParameterValue if any connection parameters are
            incorrect or if failed to connect to the Libvirt uri.
    :raises: LibvirtError if failed to connect to the Libvirt uri.
    """

    driver_info = _parse_driver_info(task.node)
    conn = _get_libvirt_connection(driver_info)
    driver_info['macs'] = driver_utils.get_node_mac_addresses(task)
    node_macs = {_normalize_mac(mac)
                 for mac in driver_info['macs']}

    full_node_list = conn.listAllDomains()

    for domain in full_node_list:
        LOG.debug("Checking Domain: %s's Mac address." % domain.name())
        parsed = ET.fromstring(domain.XMLDesc())
        domain_macs = {_normalize_mac(
                       el.attrib['address']) for el in parsed.iter('mac')}

        found_macs = domain_macs & node_macs  # this is intersection of sets
        if found_macs:
            LOG.debug("Found MAC addresses: %s "
                      "for node: %s" % (found_macs, driver_info['uuid']))
            return domain

    raise exception.NodeNotFound(
        _("Can't find domain with specified MACs: %(macs)s "
          "for node %(node)s.") %
        {'macs': driver_info['macs'], 'node': driver_info['uuid']})


def _parse_driver_info(node):
    """Gets the information needed for accessing the node.

    :param node: the Node of interest.
    :returns: dictionary of information.
    :raises: MissingParameterValue if any required parameters are missing.
    :raises: InvalidParameterValue if any required parameters are incorrect.
    """

    info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "LibvirtPowerDriver requires the following parameters to be set in"
            "node's driver_info: %s.") % missing_info)

    uri = info.get('libvirt_uri')
    sasl_username = info.get('sasl_username')
    sasl_password = info.get('sasl_password')
    ssh_key_filename = info.get('ssh_key_filename')

    if sasl_username and sasl_password and ssh_key_filename:
        raise exception.InvalidParameterValue(_(
            "LibvirtPower requires one and only one of the authentication, "
            "(sasl_username, sasl_password) or ssh_key_filename to be set."))

    if ssh_key_filename and not os.path.isfile(ssh_key_filename):
        raise exception.InvalidParameterValue(_(
            "SSH key file %s not found.") % ssh_key_filename)

    res = {
        'libvirt_uri': uri,
        'uuid': node.uuid,
        'sasl_username': sasl_username,
        'sasl_password': sasl_password,
        'ssh_key_filename': ssh_key_filename,
    }

    return res


def _power_on(domain):
    """Power ON this domain.

    :param domain: libvirt domain object.
    :returns: one of ironic.common.states POWER_ON or ERROR.
    :raises: LibvirtError if failed to connect to start domain.
    """

    current_pstate = _get_power_state(domain)
    if current_pstate == states.POWER_ON:
        return current_pstate

    try:
        domain.create()
    except libvirt.libvirtError as e:
        raise f_exc.LibvirtError(err=e)

    current_pstate = _get_power_state(domain)
    if current_pstate == states.POWER_ON:
        return current_pstate
    else:
        return states.ERROR


def _power_off(domain):
    """Power OFF this domain.

    :param domain: libvirt domain object.
    :returns: one of ironic.common.states POWER_OFF or ERROR.
    :raises: LibvirtError if failed to destroy domain.
    """

    current_pstate = _get_power_state(domain)
    if current_pstate == states.POWER_OFF:
        return current_pstate

    try:
        domain.destroy()
    except libvirt.libvirtError as e:
        raise f_exc.LibvirtError(err=e)

    current_pstate = _get_power_state(domain)
    if current_pstate == states.POWER_OFF:
        return current_pstate
    else:
        return states.ERROR


def _power_cycle(domain):
    """Power cycles a node.

    :param domain: libvirt domain object.
    :raises: PowerStateFailure if it failed to set power state to POWER_ON.
    :raises: LibvirtError if failed to power cycle domain.
    """

    try:
        _power_off(domain)
        state = _power_on(domain)
    except libvirt.libvirtError as e:
        raise f_exc.LibvirtError(err=e)

    if state != states.POWER_ON:
        raise exception.PowerStateFailure(pstate=states.POWER_ON)


def _get_power_state(domain):
    """Get the current power state of domain.

    :param domain: libvirt domain object.
    :returns: power state. One of :class:`ironic.common.states`.
    :raises: LibvirtErr if failed to get doamin status.
    """

    try:
        if domain.isActive():
            return states.POWER_ON
    except libvirt.libvirtError as e:
        raise f_exc.LibvirtError(err=e)

    return states.POWER_OFF


def _get_boot_device(domain):
    """Get the current boot device.

    :param domain: libvirt domain object.
    :returns: boot device.
    """

    parsed = ET.fromstring(domain.XMLDesc())
    boot_devs = parsed.findall('.//os/boot')
    boot_dev = boot_devs[0].attrib['dev']

    return boot_dev


def _set_boot_device(conn, domain, device):
    """Set the boot device.

    :param conn: active libvirt connection.
    :param domain: libvirt domain object.
    :raises: LibvirtError if failed update domain xml.
    """

    parsed = ET.fromstring(domain.XMLDesc())
    os = parsed.find('os')
    boot_list = os.findall('boot')

    # Clear boot list
    for boot_el in boot_list:
        os.remove(boot_el)

    boot_el = ET.SubElement(os, 'boot')
    boot_el.set('dev', device)

    try:
        conn.defineXML(ET.tostring(parsed))
    except libvirt.libvirtError as e:
        raise f_exc.LibvirtError(err=e)


class LibvirtPower(base.PowerInterface):
    """Libvirt Power Interface.

    This PowerInterface class provides a mechanism for controlling the power
    state of virtual machines via libvirt.

    NOTE: This driver supports different hypervisor types like
    openvz, vmware, hyperv, qemu, virtualbox xen.
    NOTE: This driver support multi node operations as well.
    """

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that the node's 'driver_info' is valid.

        Check that the node's 'driver_info' contains the requisite fields
        and that an Libvirt connection to the node can be established.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect or if failed to connect to the libvirt socket.
        :raises: MissingParameterValue if no ports are enrolled for the given
                 node.
       """

        if not driver_utils.get_node_mac_addresses(task):
            raise exception.MissingParameterValue(
                _("Node %s does not have any port associated with it."
                  ) % task.node.uuid)
        driver_info = _parse_driver_info(task.node)
        try:
            _get_libvirt_connection(driver_info)
        except f_exc.LibvirtError:
            LOG.error(_LE("Failed to get libvirt connection node %(node)s"),
                      {'node': task.node.uuid})
            raise exception.InvalidParameterValue(_("Libvirt connection cannot"
                                                    " be established"))

    def get_power_state(self, task):
        """Get the current power state of the task's node.

        Poll the host for the current power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: power state. One of :class:`ironic.common.states`.
        :raises: InvalidParameterValue if any connection parameters are
                 incorrect.
        :raises: NodeNotFound if could not find a VM corresponding to any
                 of the provided MACs.
        :raises: LibvirtError if failed to connect to the Libvirt uri.
        """

        domain = _get_domain_by_macs(task)
        return _get_power_state(domain)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        Set the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect, or if the desired power state is invalid.
        :raises: MissingParameterValue when a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :raises: PowerStateFailure if it failed to set power state to pstate.
        :raises: LibvirtError if failed to connect to the Libvirt uri.
        """

        domain = _get_domain_by_macs(task)
        if pstate == states.POWER_ON:
            state = _power_on(domain)
        elif pstate == states.POWER_OFF:
            state = _power_off(domain)
        else:
            raise exception.InvalidParameterValue(
                _("set_power_state called with invalid power state %s."
                  ) % pstate)

        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        Power cycles a node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect.
        :raises: MissingParameterValue when a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :raises: PowerStateFailure if it failed to set power state to POWER_ON.
        :raises: LibvirtError if failed to connect to the Libvirt uri.
        """

        domain = _get_domain_by_macs(task)

        _power_cycle(domain)

        state = _get_power_state(domain)

        if state != states.POWER_ON:
            raise exception.PowerStateFailure(pstate=states.POWER_ON)


class LibvirtManagement(base.ManagementInterface):

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Check that 'driver_info' contains Libvirt URI.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        """

        _parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """

        return list(_BOOT_DEVICES_MAP.keys())

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for the task's node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False. Ignored by this driver.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified or if any connection parameters are incorrect.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :raises: LibvirtError if failed to connect to the Libvirt uri.
        """

        domain = _get_domain_by_macs(task)
        driver_info = _parse_driver_info(task.node)
        conn = _get_libvirt_connection(driver_info)
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

        boot_device_map = _BOOT_DEVICES_MAP
        _set_boot_device(conn, domain, boot_device_map[device])

    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Provides the current boot device of the node. Be aware that not
        all drivers support this.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if any connection parameters are
            incorrect.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: NodeNotFound if could not find a VM corresponding to any
            of the provided MACs.
        :returns: a dictionary containing:
            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.
        :raises: LibvirtError if failed to connect to the Libvirt uri.
        """

        domain = _get_domain_by_macs(task)

        response = {'boot_device': None, 'persistent': None}
        response['boot_device'] = _get_boot_device(domain)
        return response

    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented by this driver.

        :param task: a TaskManager instance.

        """

        raise NotImplementedError()

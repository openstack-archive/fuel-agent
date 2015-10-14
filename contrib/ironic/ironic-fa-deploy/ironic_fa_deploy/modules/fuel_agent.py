# Copyright 2015 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Fuel Agent deploy driver.
"""

import json
import os
import tempfile

from oslo_config import cfg
from oslo_utils import excutils
import six

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.openstack.common import fileutils
from ironic.openstack.common import log
from ironic.openstack.common import loopingcall

agent_opts = [
    cfg.StrOpt('pxe_config_template',
               default=os.path.join(os.path.dirname(__file__),
                    'fuel_config.template'),
               help='Template file for PXE configuration.'),
    cfg.StrOpt('deploy_kernel',
               help='UUID (from Glance) of the default deployment kernel.'),
    cfg.StrOpt('deploy_ramdisk',
               help='UUID (from Glance) of the default deployment ramdisk.'),
    cfg.StrOpt('deploy_squashfs',
               help='UUID (from Glance) of the default deployment root FS.'), ]

CONF = cfg.CONF
CONF.register_opts(agent_opts, group='fuel')

LOG = log.getLogger(__name__)

REQUIRED_PROPERTIES = {}
OTHER_PROPERTIES = {
    'deploy_kernel': _('UUID (from Glance) of the deployment kernel.'),
    'deploy_ramdisk': _('UUID (from Glance) of the deployment ramdisk.'),
    'deploy_squashfs': _('UUID (from Glance) of the deployment root FS image '
                         'mounted at boot time.'),
    'fuel_username': _('SSH username; default is "root" Optional.'),
    'fuel_key_filename': _('Name of SSH private key file; default is '
                           '"/etc/ironic/fuel_key". Optional.'),
    'fuel_ssh_port': _('SSH port; default is 22. Optional.'),
    'fuel_deploy_script': _('path to Fuel Agent executable entry point; '
                            'default is "provision" Optional.'),
}
COMMON_PROPERTIES = OTHER_PROPERTIES

FUEL_AGENT_PROVISION_TEMPLATE = {
    "profile": "",
    "ks_meta": {
        "pm_data": {
            "kernel_params": "",
            "ks_spaces": None
        }
    }
}


def _parse_driver_info(node):
    """Gets the information needed for accessing the node.

    :param node: the Node object.
    :returns: dictionary of information.
    :raises: InvalidParameterValue if any required parameters are incorrect.
    :raises: MissingParameterValue if any required parameters are missing.

    """
    info = node.driver_info
    d_info = {}
    error_msgs = []

    d_info['username'] = info.get('fuel_username', 'root')
    d_info['key_filename'] = info.get('fuel_key_filename',
                                      '/etc/ironic/fuel_key')

    if not os.path.isfile(d_info['key_filename']):
        error_msgs.append(_("SSH key file %s not found.") %
                          d_info['key_filename'])

    try:
        d_info['port'] = int(info.get('fuel_ssh_port', 22))
    except ValueError:
        error_msgs.append(_("'fuel_ssh_port' must be an integer."))

    if error_msgs:
        msg = (_('The following errors were encountered while parsing '
                 'driver_info:\n%s') % '\n'.join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    d_info['script'] = info.get('fuel_deploy_script', 'provision')

    return d_info


def _get_tftp_image_info(node):
    params = _get_boot_files(node)
    return pxe_utils.get_deploy_kr_info(node.uuid, params)


def _get_deploy_data(context, image_source):
    glance = image_service.GlanceImageService(version=2, context=context)
    image_props = glance.show(image_source).get('properties', {})
    LOG.debug('Image %s properties are: %s', image_source, image_props)
    try:
        disk_data = json.loads(image_props['mos_disk_info'])
    except KeyError:
        raise exception.MissingParameterValue(_('Image %s does not contain '
                                              'disk layout data.') %
                                              image_source)
    except ValueError:
        raise exception.InvalidParameterValue(_('Invalid disk layout data for '
                                                'image %s') % image_source)
    data = FUEL_AGENT_PROVISION_TEMPLATE.copy()
    data['ks_meta']['pm_data']['ks_spaces'] = disk_data
    return data


@image_cache.cleanup(priority=25)
class AgentTFTPImageCache(image_cache.ImageCache):
    def __init__(self, image_service=None):
        super(AgentTFTPImageCache, self).__init__(
            CONF.pxe.tftp_master_path,
            # MiB -> B
            CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            CONF.pxe.image_cache_ttl * 60,
            image_service=image_service)


def _cache_tftp_images(ctx, node, pxe_info):
    """Fetch the necessary kernels and ramdisks for the instance."""
    fileutils.ensure_tree(
        os.path.join(CONF.pxe.tftp_root, node.uuid))
    LOG.debug("Fetching kernel and ramdisk for node %s",
              node.uuid)
    deploy_utils.fetch_images(ctx, AgentTFTPImageCache(), pxe_info.values())


def build_instance_info_for_deploy(task):
    """Build instance_info necessary for deploying to a node.

    :param task: a TaskManager object containing the node
    :returns: a dictionary containing the properties to be updated
        in instance_info
    :raises: exception.ImageRefValidationFailed if image_source is not
        Glance href and is not HTTP(S) URL.
    """
    node = task.node
    instance_info = node.instance_info

    image_source = instance_info['image_source']
    if service_utils.is_glance_image(image_source):
        glance = image_service.GlanceImageService(version=2,
                                                  context=task.context)
        image_info = glance.show(image_source)
        swift_temp_url = glance.swift_temp_url(image_info)
        LOG.debug('Got image info: %(info)s for node %(node)s.',
                  {'info': image_info, 'node': node.uuid})
        instance_info['image_url'] = swift_temp_url
        instance_info['image_checksum'] = image_info['checksum']
        instance_info['image_disk_format'] = image_info['disk_format']
        instance_info['image_container_format'] = (
            image_info['container_format'])
    else:
        try:
            image_service.HttpImageService().validate_href(image_source)
        except exception.ImageRefValidationFailed:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Agent deploy supports only HTTP(S) URLs as "
                              "instance_info['image_source']. Either %s "
                              "is not a valid HTTP(S) URL or "
                              "is not reachable."), image_source)
        instance_info['image_url'] = image_source

    return instance_info


def _create_rootfs_link(task):
    """Create Swift temp url for deployment root FS."""
    rootfs = _get_boot_files(task.node)['deploy_squashfs']

    if service_utils.is_glance_image(rootfs):
        glance = image_service.GlanceImageService(version=2,
                                                  context=task.context)
        image_info = glance.show(rootfs)
        temp_url = glance.swift_temp_url(image_info)
        temp_url += '&filename=/root.squashfs'
        return temp_url

    try:
        image_service.HttpImageService().validate_href(rootfs)
    except exception.ImageRefValidationFailed:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Agent deploy supports only HTTP URLs as "
                          "driver_info['deploy_squashfs']. Either %s "
                          "is not a valid HTTP URL or "
                          "is not reachable."), rootfs)
    return rootfs


def _build_pxe_config_options(task, pxe_info):
    """Builds the pxe config options for booting agent.

    This method builds the config options to be replaced on
    the agent pxe config template.

    :param task: a TaskManager instance
    :param pxe_info: A dict containing the 'deploy_kernel' and
        'deploy_ramdisk' for the agent pxe config template.
    :returns: a dict containing the options to be applied on
    the agent pxe config template.
    """
    ironic_api = (CONF.conductor.api_url or
                  keystone.get_service_url()).rstrip('/')

    agent_config_opts = {
        'deployment_aki_path': pxe_info['deploy_kernel'][1],
        'deployment_ari_path': pxe_info['deploy_ramdisk'][1],
        'rootfs-url': _create_rootfs_link(task),
        'deployment_id': task.node.uuid,
        'api-url': ironic_api,
    }

    return agent_config_opts


def _prepare_pxe_boot(task):
    """Prepare the files required for PXE booting the agent."""
    pxe_info = _get_tftp_image_info(task.node)
    pxe_options = _build_pxe_config_options(task, pxe_info)
    pxe_utils.create_pxe_config(task,
                                pxe_options,
                                CONF.fuel.pxe_config_template)
    _cache_tftp_images(task.context, task.node, pxe_info)


def _do_pxe_boot(task, ports=None):
    """Reboot the node into the PXE ramdisk.

    :param task: a TaskManager instance
    :param ports: a list of Neutron port dicts to update DHCP options on. If
        None, will get the list of ports from the Ironic port objects.
    """
    dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
    provider = dhcp_factory.DHCPFactory()
    provider.update_dhcp(task, dhcp_opts, ports)
    manager_utils.node_set_boot_device(task, boot_devices.PXE, persistent=True)
    manager_utils.node_power_action(task, states.REBOOT)


def _clean_up_pxe(task):
    """Clean up left over PXE and DHCP files."""
    pxe_info = _get_tftp_image_info(task.node)
    for label in pxe_info:
        path = pxe_info[label][1]
        utils.unlink_without_raise(path)
    AgentTFTPImageCache().clean_up()
    pxe_utils.clean_up_pxe_config(task)


def _ssh_execute(ssh, cmd, ssh_params):
    # NOTE(yuriyz): this ugly code is work-around against paramiko with
    # eventlet issues
    LOG.debug('Running cmd (SSH): %s', cmd)
    stdin_stream, stdout_stream, stderr_stream = ssh.exec_command(cmd)
    paramiko_channel = stdout_stream.channel
    paramiko_channel.setblocking(0)
    stdout_io = six.moves.StringIO()
    stderr_io = six.moves.StringIO()

    def _wait_execution(mutable, channel):
        try:
            stdout_data = channel.recv(1048576)
        except Exception:
            LOG.debug('No data from SSH stdout.')
        else:
            LOG.debug('Got %d from SSH stdout.', len(stdout_data))
            stdout_io.write(stdout_data)

        try:
            stderr_data = channel.recv_stderr(1048576)
        except Exception:
            LOG.debug('No data from SSH stderr.')
        else:
            LOG.debug('Got %d from SSH stderr.', len(stderr_data))
            stderr_io.write(stderr_data)

        if channel.exit_status_ready():
            raise loopingcall.LoopingCallDone()

        try:
            ssh = utils.ssh_connect(ssh_params)
        except exception.SSHConnectFailed:
            mutable['error'] = True
            raise loopingcall.LoopingCallDone()
        else:
            ssh.close()

    error = {'error': False}
    timer = loopingcall.FixedIntervalLoopingCall(_wait_execution, error,
                                                 paramiko_channel)
    timer.start(interval=60).wait()
    stdout = stdout_io.getvalue()
    stderr = stderr_io.getvalue()
    LOG.debug('SSH stdout is: "%s"', stdout)
    LOG.debug('SSH stderr is: "%s"', stderr)

    if error['error']:
        message = _('connection to the node lost')
        raise exception.SSHCommandFailed(cmd=message)

    exit_status = paramiko_channel.recv_exit_status()
    if exit_status != 0:
        message = _('wrong exit status %d') % exit_status
        raise exception.SSHCommandFailed(cmd=message)

    return stdout, stderr


def _sftp_upload(sftp, data, path):
    with tempfile.NamedTemporaryFile(dir=CONF.tempdir) as f:
        f.write(data)
        f.flush()
        sftp.put(f.name, path)


def _get_boot_files(node):
    d_info = node.driver_info
    params = {
        'deploy_kernel': d_info.get('deploy_kernel',
                                    CONF.fuel.deploy_kernel),
        'deploy_ramdisk': d_info.get('deploy_ramdisk',
                                     CONF.fuel.deploy_ramdisk),
        'deploy_squashfs': d_info.get('deploy_squashfs',
                                      CONF.fuel.deploy_squashfs),
    }
    return params


class FuelAgentDeploy(base.DeployInterface):
    """Interface for deploy-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the properties of the supplied node
        contain the required information for this driver to deploy images to
        the node.

        :param task: a TaskManager instance
        :raises: MissingParameterValue
        """
        node = task.node
        params = _get_boot_files(node)
        error_msg = _('Node %s failed to validate deploy image info. Some '
                      'parameters were missing') % node.uuid
        deploy_utils.check_for_missing_params(params, error_msg)

        _parse_driver_info(node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Perform the necessary work to deploy an image onto the specified node.
        This method will be called after prepare(), which may have already
        performed any preparatory steps, such as pre-caching some data for the
        node.

        :param task: a TaskManager instance.
        :returns: status of the deploy. One of ironic.common.states.
        """
        _do_pxe_boot(task)
        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: status of the deploy. One of ironic.common.states.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        node = task.node
        _prepare_pxe_boot(task)

        node.instance_info = build_instance_info_for_deploy(task)
        node.save()

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver. It should erase
        anything cached by the `prepare` method.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `tear_down`.

        :param task: a TaskManager instance.
        """
        _clean_up_pxe(task)

    def take_over(self, task):
        pass


class FuelAgentVendor(base.VendorInterface):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def validate(self, task, method, **kwargs):
        """Validate the driver-specific Node deployment info.

        :param task: a TaskManager instance
        :param method: method to be validated
        """
        _parse_driver_info(task.node)
        if not kwargs.get('status'):
            raise exception.MissingParameterValue(_('Unknown Fuel Agent status'
                                                    ' on a node.'))
        if not kwargs.get('address'):
            raise exception.MissingParameterValue(_('Fuel Agent must pass '
                                                    'address of a node.'))

    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def pass_deploy_info(self, task, **kwargs):
        """Continues the deployment of baremetal node."""

        node = task.node
        task.process_event('resume')
        err_msg = _('Failed to continue deployment with Fuel Agent.')

        agent_status = kwargs.get('status')
        if agent_status != 'ready':
            LOG.error(_LE('Deploy failed for node %(node)s. Fuel Agent is not '
                      'in ready state, error: %(error)s'), {'node': node.uuid,
                      'error': kwargs.get('error_message')})
            deploy_utils.set_failed_state(task, err_msg)
            return

        params = _parse_driver_info(node)
        params['host'] = kwargs.get('address')
        cmd = ('%s --data_driver ironic  --config-file '
               '/etc/fuel-agent/fuel-agent.conf' % params.pop('script'))
        if CONF.debug:
            cmd += ' --debug'
        instance_info = node.instance_info

        try:
            deploy_data = _get_deploy_data(task.context,
                                           instance_info['image_source'])

            image_data = {"/": {"uri": instance_info['image_url'],
                                "format": "raw",
                                "container": "raw"}}

            deploy_data['ks_meta']['image_data'] = image_data

            ssh = utils.ssh_connect(params)
            sftp = ssh.open_sftp()
            _sftp_upload(sftp, json.dumps(deploy_data), '/tmp/provision.json')

            # swift configdrive store should be disabled
            configdrive = instance_info.get('configdrive')
            if configdrive is not None:
                _sftp_upload(sftp, configdrive, '/tmp/config-drive.img')

            _ssh_execute(ssh, cmd, params)
            LOG.info(_LI('Fuel Agent pass on node %s'), node.uuid)
            manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                               persistent=True)
            manager_utils.node_power_action(task, states.REBOOT)
        except Exception as e:
            msg = (_('Deploy failed for node %(node)s. Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            LOG.error(msg)
            deploy_utils.set_failed_state(task, msg)
        else:
            task.process_event('done')
            LOG.info(_LI('Deployment to node %s done'), task.node.uuid)

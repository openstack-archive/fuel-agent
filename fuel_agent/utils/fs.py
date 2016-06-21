# Copyright 2014 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import tempfile

from oslo_log import log as logging
import six

from fuel_agent import errors
from fuel_agent.utils import utils


LOG = logging.getLogger(__name__)
MAX_MKFS_TRIES = 5


def format_fs_label(label):
    """Format filesystem label to match mkfs format

    Labels longer than 12 will be truncated to 12 first characters because of
    xfs limitations
    """
    if not label:
        return ''
    else:
        return ' -L {0} '.format(label[:12])


def make_fs(fs_type, fs_options, fs_label, dev):
    # NOTE(agordeev): notice the different flag to force the fs creating
    #                ext* uses -F flag, xfs/mkswap uses -f flag.
    cmd_line = []
    cmd_name = 'mkswap'
    if fs_type != 'swap':
        cmd_name = 'mkfs.%s' % fs_type
    if fs_type == 'xfs':
        # NOTE(agordeev): force xfs creation.
        # Othwerwise, it will fail to proceed if filesystem exists.
        fs_options += ' -f '
    if fs_type == 'swap':
        fs_options += ' -f '
    cmd_line.append(cmd_name)
    for opt in (fs_options, format_fs_label(fs_label)):
        cmd_line.extend([s for s in opt.split(' ') if s])
    cmd_line.append(dev)

    # NOTE(dbilunov): make sure the newly-created fs can
    # be observed by blkid. Currently known problem is
    # that generated UUID could possibly collide with
    # minix filesystem magic (0x8f13)
    mkfs_ok = False
    for _ in six.moves.range(MAX_MKFS_TRIES):
        utils.execute(*cmd_line)
        try:
            utils.execute('blkid', '-c', '/dev/null', '-o', 'value',
                          '-s', 'UUID', dev)
        except errors.ProcessExecutionError:
            LOG.warning('blkid has failed on %s, retrying...', dev)
        else:
            mkfs_ok = True
            break
    if not mkfs_ok:
        raise errors.FsUtilsError('Cannot get UUID of a newly-created ' +
                                  '{0} on {1}'.format(fs_type, dev))


def extend_fs(fs_type, fs_dev):
    if fs_type in ('ext2', 'ext3', 'ext4'):
        # ext3,4 file system can be mounted
        # must be checked with e2fsck -f
        utils.execute('e2fsck', '-yf', fs_dev, check_exit_code=[0])
        utils.execute('resize2fs', fs_dev, check_exit_code=[0])
        utils.execute('e2fsck', '-pf', fs_dev, check_exit_code=[0])
    elif fs_type == 'xfs':
        # xfs file system must be mounted
        utils.execute('xfs_growfs', fs_dev, check_exit_code=[0])
    else:
        raise errors.FsUtilsError('Unsupported file system type')


def mount_fs(fs_type, fs_dev, fs_mount, opts=None):
    fs_type = ('-t', fs_type) if fs_type is not None else ()
    opts = ('-o', opts) if opts is not None else ()
    fs_dev = (fs_dev,) if fs_dev is not None else ()
    cmd = ('mount',) + fs_type + opts + fs_dev + (fs_mount,)
    utils.execute(*cmd, check_exit_code=[0])


def mount_bind(chroot, path, path2=None):
    if not path2:
        path2 = path
    utils.execute('mount', '--bind', path, chroot + path2,
                  check_exit_code=[0])


def umount_fs(fs_mount, try_lazy_umount=False):
    try:
        utils.execute('mountpoint', '-q', fs_mount, check_exit_code=[0])
    except errors.ProcessExecutionError:
        LOG.warning('%s is not a mountpoint, skipping umount', fs_mount)
    else:
        LOG.debug('Trying to umount {0}'.format(fs_mount))
        try:
            utils.execute('umount', fs_mount, check_exit_code=[0])
        except errors.ProcessExecutionError as e:
            if try_lazy_umount:
                LOG.warning('Error while umounting {0} '
                            'exc={1}'.format(fs_mount, e.message))
                LOG.debug('Trying lazy umounting {0}'.format(fs_mount))
                utils.execute('umount', '-l', fs_mount, check_exit_code=[0])
            else:
                raise


def get_fs_type(device):
    output = utils.execute('blkid', '-o', 'value', '-s', 'TYPE',
                           '-c', '/dev/null', device)[0]
    return output.strip()


def mount_fs_temp(fs_type, fs_dev, tmpdir=None, suffix=''):
    mount_point = tempfile.mkdtemp(dir=tmpdir, suffix=suffix)
    mount_fs(fs_type, fs_dev, mount_point)
    return mount_point

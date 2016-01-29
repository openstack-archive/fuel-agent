Fuel Agent driver for Ironic
============================

``ironic-fa-deploy`` package adds support of Fuel Agent to OpenStack Ironic.
Ironic [#]_ is baremetal provisioning service with support of multiple hardware
types. Ironic architecture is able to work with deploy agents. Deploy agent
is a service that does provisioning tasks on the node side. Deploy agent should
be integrated into bootstrap ramdisk image.
``ironic-fa-deploy`` contains pluggable drivers code for Ironic that uses
Fuel Agent as deploy agent. Current implementation requires and tested with
Ironic Liberty release.
There are two drivers: ``fuel_ipmitool`` and ``fuel_ssh``. ``fuel_ipmitool``
uses "ipmitool" utility for node power control and management via standard
Ironic interfaces and Fuel Agent via Ironic deploy driver's interface.
``fuel_ssh`` intended for virtual developers' environments.

Node enrollment process with Fuel Agent
---------------------------------------

``fuel_ipmitool`` driver used in example.

1. Enable the driver, add ``fuel_ipmitool`` to the list of ``enabled_drivers``
   in ``[DEFAULT]`` section of ``/etc/ironic/ironic.conf``.

2. Generate RSA key pair for SSH access to bootstrap system on the node.

3. Create bootstrap files with Fuel Agent via ``fuel-bootstrap-image-builder``
   script from ``fuel-main`` [#]_ project, public key should be injected into
   bootstrap system. We should obtain three files as result: kernel, initrd
   image and root FS image.

4. Upload kernel, initrd image and root FS image to the Glance image service.

.. note:: Fuel Agent driver requires OpenStack Swift or Ceph RADOS Gateway
          as Glance backend.

5. Create a node in Ironic with ``fuel_ipmitool`` driver and associate port
   with the node::

    ironic node-create -d fuel_ipmitool

    ironic port-create -n <node uuid> -a <MAC address>

6. Set IPMI address and credentials as described in the Ironic documentation
   [#]_.

7. Set Fuel Agent related driver's parameters for the node::

    ironic node-update <node uuid> add driver_info/deploy_kernel=KERNEL \
           driver_info/deploy_ramdisk=INITRD \
           driver_info/deploy_squashfs=ROOTFS \
           driver_info/fuel_key_filename=PRIVATE_KEY

Replace KERNEL, INITRD, ROOTFS with Glance UUIDs of deploy images, PRIVATE_KEY
with path to private key file.

8. Place disks scheme in Nailgun format to the metadata of Glance instance
   image with ``fuel_disk_info`` key, example::

    glance image-update <image uuid> --property fuel_disk_info='[{"name": "sda",
       "extra": [], "free_space": 11000, "type": "disk", "id": "vda",
       "size": 11000, "volumes": [{"mount": "/", "type": "partition",
       "file_system": "ext4", "size": 10000}]}]'

After steps above the node is ready for deploying. User can invoke
``nova boot`` command for deploying an instance image.


TODO:

* Add custom boot interface and refactor the drivers code with boot
  interface [#]_.

* Add cleaning support.

* Add RAID support via Ironic RAID interface.

.. [#] https://wiki.openstack.org/wiki/Ironic
.. [#] https://github.com/openstack/fuel-main
.. [#] http://docs.openstack.org/developer/ironic/deploy/install-guide.html
.. [#] https://specs.openstack.org/openstack/ironic-specs/specs/4.2/new-boot-interface.html

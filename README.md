Team and repository tags
========================

[![Team and repository tags](http://governance.openstack.org/badges/fuel-agent.svg)](http://governance.openstack.org/reference/tags/index.html)

<!-- Change things from this point on -->

fuel-agent README
=================

## Table of Contents

- [Overview](#overview)
- [Structure](#structure)
- [Usage](#usage)
- [Development](#development)
- [Core Reviewers](#core-reviewers)
- [Contributors](#contributors)

## Overview

fuel-agent is nothing more than just a set of data driven executable
scripts.
- One of these scripts is used for building operating system images. One can run
this script on wherever needed passing a set of repository URIs and a set of
package names that are to be installed into the image.
- Another script is used for the actual provisioning. This script being installed
into a ramdisk (live image) can be run to provision an operating system on a hard drive.
When running one needs to pass input data that contain information about disk
partitions, initial node configuration, operating system image location, etc.
This script is to prepare disk partitions according to the input data, download
operating system images and put these images on partitions.


### Motivation
- Native operating installation tools like anaconda and debian-installer are:
  * hard to customize (if the case is really non-trivial)
  * hard to troubleshoot (it is usually quite difficult to understand which log file
  contains necessary information and how to run those tools in debug mode)
- Image based approach to operating system installation allows to make this
  process really scalable. For example, we can use BitTorrent based image
  delivery scheme when provisioning that makes the process easily scalable up
  to thousands of nodes.
- When provisioning we can check hash sum of the image and use other validation
  mechanisms that can make the process more stable.


### Designed to address requirements
- Support various input data formats (pluggable input data drivers)
- Support plain partitions, lvm, md, root on lvm, etc.
- Be able to do initial node configuration (network, mcollective, puppet, ntp)
- Be able to deploy standalone OS (local kernel, local bootloader)
- Support various image storages (tftp, http, torrent)
- Support various image formats (compressed, disk image, fs image, tar image)

### Design outline
- Use cloud-init for initial node configuration
- Avoid using parted and lvm native python bindings (to make it easy to
  troubleshoot and modify for deployment engineers)
- No REST API, just executable entry points (like /usr/bin/fa_*)
- Passing input data either via file (--input_data_file) or CLI parameter (--input_data)
- Detailed logging of all components


## Structure

### Basic Repository Layout

```
fuel-agent
├── cloud-init-templates
├── contrib
├── debian
├── etc
├── fuel_agent
│   ├── cmd
│   ├── drivers
│   ├── objects
│   ├── openstack
│   ├── tests
│   ├── utils
├── README.md
├── LICENSE
├── requirements.txt
├── run_tests.sh
├── setup.cfg
├── setup.py
├── specs
├── test-requirements.txt
```

### root

The root level contains important repository documentation and license information.
It also contais files which are typical for the infracture of python project such
as requirements.txt and setup.py

### cloud-init-templates

This folder contains Jinja2 templates to prepare [cloud-init](https://cloudinit.readthedocs.org/en/latest/) related data for [nocloud](http://cloudinit.readthedocs.org/en/latest/topics/datasources.html#no-cloud) [datasource](http://cloudinit.readthedocs.org/en/latest/topics/datasources.html#what-is-a-datasource).

### contrib

This directory contains third party code that is not a part of fuel-agent itself but
can be used together with fuel-agent.

### debian

This folder contains the DEB package specification.
Included debian rules are mainly suitable for Ubuntu 12.04 or higher.

### etc

This folder contains the sample config file for fuel-agent. Every parameter is well documented.
We use oslo-config as a configuration module.

### fuel_agent

This folder contains the python code: drivers, objects, unit tests and utils, manager and entry points.

- fuel_agent/cmd/agent.py
    * That is where executable entry points are. It reads input data and
      instantiates Manager class with these data.
- fuel_agent/manager.py
    * That is the file where the top level agent logic is implemented.
      It contains all those methods which do something useful (do_*)
- fuel_agent/drivers
    * That is where input data drivers are located.
      (Nailgun, NailgunBuildImage, Simple etc.)
      Data drivers convert json into a set of python objects.
- fuel_agent/objects
    * Here is the place where python objects are defined. fuel-agent manager
      does not understand any particular data format except these objects.
      For example, to do disk partitioning we need PartitionScheme object.
      PartitionScheme object in turn contains disk labels, plain partitions,
      lvm, md, fs objects. This PartitionScheme object is to be created by input
      data driver.
- fuel_agent/utils
    * That is the place where we put the code which does something useful on the OS
      level. Here we have simple parted, lvm, md, grub bindings, etc.

### specs

This folder contains the RPM package specfication file.
Included RPM spec is mainly suitable for Centos 6.x or higher.


## Usage

### Use case #1 (Fuel)

fuel-agent is used in Fuel project as a part of operating system provisioning scheme.
When a user starts deployment of OpenStack cluster, the first task is to install
an operating system on slave nodes. First, Fuel runs fuel-agent on the master node
to build OS images. Once images are built, Fuel then runs fuel-agent on slave nodes
using Mcollective. Slave nodes are supposed to be booted with so called bootstrap ramdisk.
Bootstrap ramdisk is an in-memory OS where fuel-agent is installed.

Detailed documentation on this case is available here:
* [Image based provisionig](https://docs.mirantis.com/openstack/fuel/fuel-master/reference-architecture.html#image-based-provisioning)
* [fuel-agent](https://docs.mirantis.com/openstack/fuel/fuel-master/reference-architecture.html#fuel-agent)
* [Operating system provisioning](https://docs.mirantis.com/openstack/fuel/fuel-master/reference-architecture.html#operating-system-provisioning)
* [Image building](https://docs.mirantis.com/openstack/fuel/fuel-master/reference-architecture.html#image-building)

### Use case #2 (Independent on Fuel)

fuel-agent can easily be used in third party projects as a convenient operating system
provisioning tool. As described above fuel-agent is fully data driven and supports
various input data formats using pluggable input data drivers. Currently there are three
input data drivers available. Those are

- NailgunBuildImage and Nailgun
  * Build image and provisioning input data drivers used in Fuel project. To use them
  independently read Fuel documentation.
- NailgunSimpleDriver
  * fuel-agent native partitioning input data driver. It is just a de-serializer for
  fuel-agent PartitionScheme object.

In order to be able to use another specific data format one can implement his own data
driver and install it independently. fuel-agent uses stevedore to find installed drivers.
A new driver needs to be exposed via fuel_agent.driver setuptools name space. See for example
setup.cfg file where entry points are defined.

One can also take a look at ```contrib``` directory for some additional examples.


### How to install

fuel-agent can be installed either using RPM/DEB packages or using ```python setup.py install```.


## Development

fuel-agent currently is a subproject of Fuel project. So, we follow the same development
practices as Fuel itself.

* [Fuel Development Documentation](https://docs.fuel-infra.org/fuel-dev/)
* [Fuel How to Contribute](https://wiki.openstack.org/wiki/Fuel/How_to_contribute)


## Core Reviewers

* [fuel-agent cores](https://review.openstack.org/#/admin/groups/995,members)


## Contributors

* [Stackalytics](http://stackalytics.com/?release=all&project_type=all&module=fuel-agent&metric=commits)

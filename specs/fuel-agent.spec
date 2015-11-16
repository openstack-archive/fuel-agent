%define name fuel-agent
%{!?version: %define version 8.0.0}
%{!?release: %define release 1}

Name: %{name}
Version: %{version}
Release: %{release}
Source0: %{name}-%{version}.tar.gz
Summary: Fuel-agent package
URL:     http://mirantis.com
License: Apache
Group: Development/Libraries
BuildRoot: %{_tmppath}/%{name}-%{version}-buildroot
Prefix: %{_prefix}
BuildRequires:  git
BuildRequires: python-setuptools
BuildRequires: python-pbr
BuildArch: noarch

Requires:    python
Requires:    python-babel
Requires:    python-eventlet
Requires:    python-jsonschema
Requires:    python-oslo-config >= 1:1.6.0
Requires:    python-oslo-serialization >= 1.0.0
Requires:    python-iso8601
Requires:    python-six
Requires:    python-stevedore
Requires:    python-jinja2
Requires:    python-requests
Requires:    python-urllib3
Requires:    PyYAML
Requires:    python-argparse
Requires:    python-pbr
Requires:    tar
Requires:    gzip
Requires:    bzip2
Requires:    openssh-clients
Requires:    mdadm
Requires:    util-linux-ng
Requires:    udev
Requires:    lvm2
Requires:    dmidecode
Requires:    parted
Requires:    cloud-utils
Requires:    e2fsprogs
Requires:    gdisk
Requires:    genisoimage
Requires:    xfsprogs
Requires:    pciutils
Requires:    ethtool
Requires:    debootstrap
Requires:    xz
Requires:    coreutils

%description
Fuel-agent package

%package -n   ironic-fa-bootstrap-configs
Summary:      Ironic bootstrap config files
Group:        Development/Libraries

%description -n  ironic-fa-bootstrap-configs
Ironic bootstrap config files with Fuel Agent


%prep
%setup -cq -n %{name}-%{version}

%build
cd %{_builddir}/%{name}-%{version} && python setup.py build


%install
cd %{_builddir}/%{name}-%{version} && python setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record=%{_builddir}/%{name}-%{version}/INSTALLED_FILES
install -d -m 755 %{buildroot}%{_sysconfdir}/fuel-agent
install -p -D -m 644 %{_builddir}/%{name}-%{version}/etc/fuel-agent/fuel-agent.conf.sample  %{buildroot}%{_sysconfdir}/fuel-agent/fuel-agent.conf
# Install template file
install -d -m 755 %{buildroot}%{_datadir}/fuel-agent/cloud-init-templates
install -p -D -m 644 %{_builddir}/%{name}-%{version}/cloud-init-templates/* %{buildroot}%{_datadir}/fuel-agent/cloud-init-templates

#ironic bootstrap config files
install -d -m 755 %{buildroot}%{_datadir}/ironic-fa-bootstrap-configs/
cp -a %{_builddir}/%{name}-%{version}/contrib/ironic/bootstrap-files/* %{buildroot}%{_datadir}/ironic-fa-bootstrap-configs/


%clean
rm -rf $RPM_BUILD_ROOT

%files -f %{_builddir}/%{name}-%{version}/INSTALLED_FILES
%defattr(-,root,root)
%config(noreplace) %{_sysconfdir}/fuel-agent/fuel-agent.conf
%{_datadir}/fuel-agent/cloud-init-templates/*

%files -n ironic-fa-bootstrap-configs
%attr(0644,root,root) %config(noreplace) %{_datadir}/ironic-fa-bootstrap-configs/*
%attr(0755,root,root) %config(noreplace) %{_datadir}/ironic-fa-bootstrap-configs/usr/bin/configure-remote-logging.sh

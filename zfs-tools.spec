# See https://docs.fedoraproject.org/en-US/packaging-guidelines/Python/#_example_spec_file

%define debug_package %{nil}

%define module_name zfs_tools
%define _name zfs-tools

%define mybuildnumber %{?build_number}%{?!build_number:1}

Name:           %{_name}
Version:        0.6.10
Release:        %{mybuildnumber}%{?dist}
Summary:        ZFS synchronization and snapshotting tools

License:        GPLv2
URL:            https://github.com/Rudd-O/%{name}
Source:         %{url}/archive/v%{version}/%{module_name}-%{version}.tar.gz

Requires:       zfs
BuildArch:      noarch
BuildRequires:  python3-devel

%global _description %{expand:
The ZFS backup tools will help you graft an entire ZFS pool as a filesystem
into a backup machine, without having to screw around snapshot names or
complicated shell commands or crontabs.}

%description %_description

%package -n zfs-shell
Summary: A minimal shell to remotely use ZFS for send and receive
%description -n zfs-shell
Use this shell (and optional contrib sudoers file) to permit access to zreplicate.

%prep
%autosetup -p1 -n %{module_name}-%{version}

%generate_buildrequires
%pyproject_buildrequires -t


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files %{module_name}
install -m755 -D bin/zfs-shell "$RPM_BUILD_ROOT"/%{_bindir}/zfs-shell
install -m644 -D contrib/sudoers.zfs-tools "$RPM_BUILD_ROOT"/%{_docdir}/zfs-shell/contrib/sudoers.zfs-tools


%check
%tox


%files -f %{pyproject_files}
%doc README.md TODO
%{_bindir}/zbackup
%{_bindir}/zflock
%{_bindir}/zreplicate
%{_bindir}/zsnap

%files -n zfs-shell
%{_bindir}/zfs-shell
%{_docdir}/zfs-shell/contrib/sudoers.zfs-tools


%changelog
* Thu Feb 22 2024 Manuel Amador <rudd-o@rudd-o.com> 0.6.10-1
- First RPM packaging release

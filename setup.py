#!/usr/bin/env python

from setuptools import setup
import os

dir = os.path.dirname(__file__)
path_to_main_file = os.path.join(dir, "src/zfstools/__init__.py")
path_to_readme = os.path.join(dir, "README.md")
for line in open(path_to_main_file):
	if line.startswith('__version__'):
		version = line.split()[-1].strip("'").strip('"')
		break
else:
	raise ValueError, '"__version__" not found in "src/zfstools/__init__.py"'
readme = open(path_to_readme).read(-1)

classifiers = [
'Development Status :: 5 - Production/Stable',
'Environment :: Console',
'Environment :: No Input/Output (Daemon)',
'Intended Audience :: System Administrators',
'License :: OSI Approved :: GNU General Public License (GPL)',
'Operating System :: POSIX :: Linux',
'Programming Language :: Python :: 2 :: Only',
'Programming Language :: Python :: 2.7',
'Topic :: System :: Filesystems',
'Topic :: Communications :: File Sharing',
'Topic :: System :: Archiving :: Backup',
'Topic :: System :: Archiving :: Mirroring',
'Topic :: Utilities',
]

setup(
	name='zfs-tools',
	version=version,
	description='ZFS synchronization and snapshotting tools',
	long_description = readme,
	author='Manuel Amador (Rudd-O)',
	author_email='rudd-o@rudd-o.com',
	license="GPL",
	url='http://github.com/Rudd-O/zfs-tools',
	package_dir=dict([
					("zfstools", "src/zfstools"),
					]),
	classifiers = classifiers,
	packages=["zfstools"],
	scripts=["bin/zreplicate", 'bin/zfs-shell', 'bin/zsnap', 'bin/zbackup', 'bin/zlock'],
	keywords="ZFS filesystems backup synchronization snapshot",
	zip_safe=False,
)

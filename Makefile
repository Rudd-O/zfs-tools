ROOT_DIR := $(shell dirname "$(realpath $(MAKEFILE_LIST))")

.PHONY = test install dist rpm srpm clean

test:
	cd $(ROOT_DIR) && \
	tox --current-env

install:
	if test x"$(DESTDIR)" = x; then echo "DESTDIR unset."; exit 1; fi
	mkdir -p $(DESTDIR)
	python3 setup.py bdist_dumb
	tar zxvmf dist/zfs-tools-*.linux-*.tar.gz -C $(DESTDIR)
	mv $(DESTDIR)/usr/local/* $(DESTDIR)/usr
	rmdir $(DESTDIR)/usr/local
	mkdir -p $(DESTDIR)/etc/sudoers.d
	cp contrib/sudoers.zfs-tools $(DESTDIR)/etc/sudoers.d/zfs-shell
	chmod 440 $(DESTDIR)/etc/sudoers.d/zfs-shell

clean:
	cd $(ROOT_DIR) && find -name '*~' -print0 | xargs -0r rm -fv && rm -fr *.tar.gz *.rpm src/*.egg-info *.egg-info dist build

dist: clean
	cd $(ROOT_DIR) || exit $$? ; python3 -m build

srpm: dist
	@which rpmbuild || { echo 'rpmbuild is not available.  Please install the rpm-build package with the command `dnf install rpm-build` to continue, then rerun this step.' ; exit 1 ; }
	cd $(ROOT_DIR) || exit $$? ; rpmbuild --define "_srcrpmdir ." -ts dist/`rpmspec -q --queryformat '%{name}-%{version}.tar.gz\n' *spec | head -1`

rpm: dist
	@which rpmbuild || { echo 'rpmbuild is not available.  Please install the rpm-build package with the command `dnf install rpm-build` to continue, then rerun this step.' ; exit 1 ; }
	cd $(ROOT_DIR) || exit $$? ; rpmbuild --define "_srcrpmdir ." --define "_rpmdir builddir.rpm" -ta dist/`rpmspec -q --queryformat '%{name}-%{version}.tar.gz\n' *spec | head -1`
	cd $(ROOT_DIR) ; mv -f builddir.rpm/*/* . && rm -rf builddir.rpm

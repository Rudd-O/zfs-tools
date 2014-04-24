nothing:
	true

install:
	if test x"$(DESTDIR)" = x; then echo "DESTDIR unset."; exit 1; fi
	python setup.py bdist_dumb
	tar zxvmf dist/zfs-tools-*.linux-*.tar.gz -C $(DESTDIR)
	mkdir -p $(DESTDIR)/etc/sudoers.d
	cp contrib/sudoers.zfs-tools $(DESTDIR)/etc/sudoers.d/zfs-tools
	chmod 440 $(DESTDIR)/etc/sudoers.d/zfs-tools

.PHONY = install

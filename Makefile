install:
        python setup.py bdist_dumb
        tar -C $(DESTDIR) zxvmf dist/zfs-tools-*.linux-*.tar.gz
	mkdir -p $(DESTDIR)/etc/sudoers.d
	cp contrib/sudoers.zfs-tools $(DESTDIR)/etc/sudoers.d/zfs-tools
	chmod 440 $(DESTDIR)/etc/sudoers.d/zfs-tools

.PHONY = install

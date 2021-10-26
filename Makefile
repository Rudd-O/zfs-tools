nothing:
	true

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

.PHONY = install

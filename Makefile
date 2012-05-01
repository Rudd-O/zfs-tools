zfslib.pyc: zfslib.py
	python -c 'import compileall ; compileall.compile_dir(dir=".",quiet=True)'

install:
	mkdir -p $(DESTDIR)/usr/bin $(DESTDIR)/usr/lib/pymodules/python2.6
	cp zfs-fetch-pool zfs-shell zmirror zsnap zreplicate $(DESTDIR)/usr/bin
	cp zfslib.py zfslib.pyc $(DESTDIR)/usr/lib/pymodules/python2.6
	mkdir -p $(DESTDIR)/etc/sudoers.d
	cp sudoers.zfs $(DESTDIR)/etc/sudoers.d/zfs
	chmod 440 $(DESTDIR)/etc/sudoers.d/zfs

.PHONY = install

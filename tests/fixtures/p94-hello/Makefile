PREFIX ?= /usr/local
DESTDIR ?=
BINDIR ?= $(PREFIX)/bin
DATADIR ?= $(PREFIX)/share
USERUNITDIR ?= $(PREFIX)/lib/systemd/user
PYTHON ?= /usr/bin/python3
# Path the unit uses at runtime; Homebrew passes the opt path so upgrades keep working.
RUNTIME_BINDIR ?= $(BINDIR)

install:
	install -Dm755 bin/p94-hello $(DESTDIR)$(BINDIR)/p94-hello
	sed -i '1s|^#!.*|#!$(PYTHON)|' $(DESTDIR)$(BINDIR)/p94-hello
	install -Dm644 share/hello.conf $(DESTDIR)$(DATADIR)/p94-hello/hello.conf
	install -d $(DESTDIR)$(USERUNITDIR)
	sed 's|@BINDIR@|$(RUNTIME_BINDIR)|' systemd/p94-hello.service.in > $(DESTDIR)$(USERUNITDIR)/p94-hello.service
	install -Dm644 completions/p94-hello.bash $(DESTDIR)$(DATADIR)/bash-completion/completions/p94-hello
	install -Dm644 completions/p94-hello.fish $(DESTDIR)$(DATADIR)/fish/vendor_completions.d/p94-hello.fish
	install -Dm644 shell/p94-hello.bash $(DESTDIR)$(DATADIR)/p94/bash.d/p94-hello.bash
	install -Dm644 shell/p94-hello.fish $(DESTDIR)$(DATADIR)/fish/vendor_conf.d/p94-hello.fish

.PHONY: install

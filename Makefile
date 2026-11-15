SHELL := /bin/bash
PY := /usr/bin/python3 -I

# Files are found, not listed, so new scripts are covered automatically.
BASH_FILES = $(sort $(shell find shell tests -type f \( -name '*.sh' -o -name '*.bash' \) 2>/dev/null) \
             $(shell grep -lsE '^#!.*[/ ]bash( |$$)' $$(find bin -type f 2>/dev/null) /dev/null))
FISH_FILES = $(sort $(shell find shell tests -type f -name '*.fish' 2>/dev/null))
PY_FILES = $(sort $(shell find lib tests -type f -name '*.py' 2>/dev/null) \
           $(shell grep -lsE '^#!.*python3' $$(find bin cmd -type f 2>/dev/null) /dev/null))

.PHONY: check check-basic check-formulae test fmt

check-basic:
	@for f in $(BASH_FILES); do bash -n "$$f" || exit 1; done
	@for f in $(FISH_FILES); do fish --no-execute "$$f" || exit 1; done
	@$(PY) -m py_compile $(PY_FILES)
	@$(PY) -m unittest discover -s tests/unit -t .
	@echo "check-basic: ok"

check: check-basic
	@command -v shellcheck >/dev/null || { echo "check: Fehler: shellcheck fehlt; installieren: brew install shellcheck" >&2; exit 1; }
	@command -v ruff >/dev/null || { echo "check: Fehler: ruff fehlt; installieren: brew install ruff" >&2; exit 1; }
	@if [ -n "$(BASH_FILES)" ]; then shellcheck -x $(BASH_FILES); fi
	@ruff check lib tests
	@ruff format --check lib tests
	@echo "check: ok"

# Formulae are checked from the tap clone, so commit and fast-forward the tap first.
check-formulae:
	@for f in Formula/*.rb; do [ -e "$$f" ] || continue; n=$$(basename "$$f" .rb); \
	  brew style --formula "weegee/p94/$$n" && brew audit --formula "weegee/p94/$$n" || exit 1; done
	@echo "check-formulae: ok"

test:
	@$(PY) -m unittest discover -s tests/unit -t . -v

fmt:
	@ruff format lib tests

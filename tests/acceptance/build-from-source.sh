#!/usr/bin/env bash
# Acceptance test: a formula builds from source with the Homebrew toolchain (AK-13).
# Builds "hello" from source, runs it and restores the state from before the test.
# One line per check: "✓ ..." passed, "✗ ..." failed. Exit 1 on any failure.
set -euo pipefail

PROG=${0##*/}
PREFIX=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}
BREW=$PREFIX/bin/brew
FORMULA=hello
FAILED=0
LQ='„' # German quotes, kept in variables because shellcheck flags them in strings
RQ='“'

pass() { printf '✓ %s\n' "$*"; }
fail() {
    printf '✗ %s\n' "$*"
    FAILED=1
}

[[ -x $BREW ]] || {
    printf '%s: Fehler: Homebrew fehlt unter %s.\n' "$PROG" "$PREFIX" >&2
    exit 1
}

LOG=$(mktemp "${TMPDIR:-/tmp}/p94-build-from-source.XXXXXX")

was_installed=0
if "$BREW" list --versions "$FORMULA" >/dev/null 2>&1; then
    was_installed=1
fi

# shellcheck disable=SC2329 # called through the EXIT trap
restore() {
    "$BREW" uninstall --force "$FORMULA" >/dev/null 2>&1 || true
    if ((was_installed)); then
        # the bottle that was there before; the test must not leave a source build behind
        if "$BREW" install "$FORMULA" >/dev/null 2>&1; then
            printf '– %s wie vorher installiert\n' "$FORMULA"
        else
            printf '⚠ %s war vorher installiert und ließ sich nicht wiederherstellen: brew install %s\n' "$FORMULA" "$FORMULA"
        fi
    fi
}
trap 'restore; rm -f "$LOG"' EXIT

if ((was_installed)); then
    "$BREW" uninstall --force "$FORMULA" >/dev/null 2>&1 || true
fi

if "$BREW" install --build-from-source "$FORMULA" >"$LOG" 2>&1; then
    pass "brew install --build-from-source $FORMULA endet mit 0"
else
    fail "brew install --build-from-source $FORMULA scheitert"
    tail -n 8 "$LOG" | sed 's/^/  /'
    exit 1
fi

if grep -q 'Pouring' "$LOG"; then
    fail "$FORMULA wurde aus einer Flasche installiert, nicht aus dem Quelltext"
else
    pass "$FORMULA aus dem Quelltext"
fi

got=$("$PREFIX/bin/$FORMULA" 2>&1 || true)
if [[ $got == "Hello, world!" ]]; then
    pass "$PREFIX/bin/$FORMULA gibt ${LQ}${got}${RQ} aus"
else
    fail "$PREFIX/bin/$FORMULA gibt ${LQ}${got}${RQ} aus statt ${LQ}Hello, world!${RQ}"
fi

exit "$FAILED"

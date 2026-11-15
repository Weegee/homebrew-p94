#!/usr/bin/env bash
# Acceptance test (AK-11): pip builds a C extension in a venv with the Homebrew toolchain.
# Needs network access to PyPI for setuptools. One line per check: "✓ ..." passed, "✗ ..." failed.
set -euo pipefail

PROG=${0##*/}
SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
PREFIX=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}
PYTHON=$PREFIX/opt/python@3.14/bin/python3.14

[[ -x $PYTHON ]] || {
    printf '%s: Fehler: %s fehlt; erst bin/p94-brew-bootstrap ausführen.\n' "$PROG" "$PYTHON" >&2
    exit 1
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/p94-pip-cext.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
cp -r "$SCRIPT_DIR/../fixtures/cext" "$WORK/cext"

export PATH=$PREFIX/bin:$PATH
if ! "$PYTHON" -m venv "$WORK/venv" >"$WORK/venv.log" 2>&1; then
    printf '✗ venv ließ sich nicht anlegen\n'
    tail -n 5 "$WORK/venv.log" | sed 's/^/  /'
    exit 1
fi
if ! "$WORK/venv/bin/pip" install --no-cache-dir "$WORK/cext" >"$WORK/pip.log" 2>&1; then
    printf '✗ pip baut die C-Erweiterung nicht\n'
    tail -n 8 "$WORK/pip.log" | sed 's/^/  /'
    exit 1
fi
got=$("$WORK/venv/bin/python" -c 'import p94cext; print(p94cext.add(2, 3))' 2>&1 || true)
if [[ $got == 5 ]]; then
    printf '✓ pip baut C-Erweiterung im venv\n'
else
    printf '✗ p94cext.add(2, 3) gibt „%s“ statt „5“\n' "$got"
    exit 1
fi

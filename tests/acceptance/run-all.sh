#!/usr/bin/env bash
# Runs all acceptance checks of the toolchain and prints one line per part.
# Exit 0 only when every part passed.
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
REPO=$(dirname "$(dirname "$SCRIPT_DIR")")
PREFIX=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}
BREW=$PREFIX/bin/brew
PASSED=0
TOTAL=0

# part LABEL COMMAND...: run, show the output of a failing part, count the result.
part() {
    local label=$1 out rc=0
    shift
    TOTAL=$((TOTAL + 1))
    out=$("$@" 2>&1) || rc=$?
    if ((rc == 0)); then
        printf '✓ %s\n' "$label"
        PASSED=$((PASSED + 1))
    else
        printf '✗ %s\n' "$label"
        printf '%s\n' "$out" | tail -n 12 | sed 's/^/  /'
    fi
}

part "Toolchain: C, C++ und clang bauen und laufen" "$SCRIPT_DIR/toolchain.sh"
part "Build aus dem Quelltext (hello)" "$SCRIPT_DIR/build-from-source.sh"
part "pip baut eine C-Erweiterung im venv" "$SCRIPT_DIR/pip-cext.sh"
part "Rust-Crate mit cc-Build-Skript" "$SCRIPT_DIR/rust-cc.sh"
part "brew p94-toolchain check" "$BREW" p94-toolchain check
part "Brewfile vollständig installiert" "$BREW" bundle check --file "$REPO/Brewfile" --no-upgrade
# sbin belongs to the PATH of the shell integration; the calling shell may not have it
part "brew doctor ohne Befunde" env PATH="$PREFIX/bin:$PREFIX/sbin:$PATH" "$BREW" doctor

if ((PASSED == TOTAL)); then
    printf '✓ Abnahme: %d von %d\n' "$PASSED" "$TOTAL"
else
    printf '✗ Abnahme: %d von %d\n' "$PASSED" "$TOTAL"
    exit 1
fi

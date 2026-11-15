#!/usr/bin/env bash
# Acceptance test for the toolchain: C and C++ programs build and run with gcc, C builds with clang.
# One line per check: "✓ ..." passed, "✗ ..." failed, "⚠ ..." warning (not part of the acceptance).
# Exit 1 on any failure.
set -euo pipefail

PROG=${0##*/}
PREFIX=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}
FAILED=0
LQ='„' # German quotes, kept in variables because shellcheck flags them in strings
RQ='“'

pass() { printf '✓ %s\n' "$*"; }
fail() {
    printf '✗ %s\n' "$*"
    FAILED=1
}
warn() { printf '⚠ %s\n' "$*"; }

[[ -x $PREFIX/bin/cc ]] || {
    printf '%s: Fehler: %s/bin/cc fehlt; erst brew install weegee/p94/steamos-sysroot.\n' "$PROG" "$PREFIX" >&2
    exit 1
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/p94-toolchain-test.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

cat >"$WORK/hello.c" <<'EOF'
#include <stdio.h>
#include <linux/version.h>
int main(void) { puts("hallo 1"); return 0; }
EOF
cat >"$WORK/hello.cpp" <<'EOF'
#include <iostream>
#include <string>
#include <vector>
int main() {
    std::vector<std::string> words{"hallo", "c++"};
    std::cout << words[0] << " " << words[1] << std::endl;
    return 0;
}
EOF

# build_run LABEL EXPECTED COMPILER SOURCE...: compile, run, compare the output; sets LAST_BIN.
LAST_BIN=
build_run() {
    local label=$1 expected=$2 compiler=$3 src=$4 bin log
    bin="$WORK/${compiler##*/}-${src##*/}.bin"
    log="$WORK/${compiler##*/}-${src##*/}.log"
    if ! "$compiler" -o "$bin" "$src" >"$log" 2>&1; then
        fail "$label: Übersetzen scheitert"
        sed 's/^/  /' "$log" | tail -n 5
        return 1
    fi
    local got
    got=$("$bin" 2>&1) || {
        fail "$label: Programm endet mit Fehler"
        return 1
    }
    if [[ $got == "$expected" ]]; then
        pass "$label: Ausgabe ${LQ}${got}${RQ}"
    else
        fail "$label: Ausgabe ${LQ}${got}${RQ} statt ${LQ}${expected}${RQ}"
        return 1
    fi
    LAST_BIN=$bin
}

build_run "cc: C-Programm" "hallo 1" "$PREFIX/bin/cc" "$WORK/hello.c" || true
build_run "gcc: C-Programm" "hallo 1" "$PREFIX/bin/gcc" "$WORK/hello.c" && GCC_BIN=$LAST_BIN || GCC_BIN=
build_run "c++: C++-Programm" "hallo c++" "$PREFIX/bin/c++" "$WORK/hello.cpp" || true
build_run "g++: C++-Programm" "hallo c++" "$PREFIX/bin/g++" "$WORK/hello.cpp" || true

if [[ -n $GCC_BIN ]] && command -v readelf >/dev/null; then
    interp=$(readelf -l "$GCC_BIN" | sed -n 's/.*Requesting program interpreter: \(.*\)\]/\1/p')
    if [[ $interp == "$PREFIX/lib/ld.so" ]]; then
        pass "gcc: Programm nutzt den Lader $interp"
    else
        warn "gcc: Programm nutzt den Lader ${interp:-unbekannt} statt $PREFIX/lib/ld.so"
    fi
fi

clang=$PREFIX/opt/llvm/bin/clang
if [[ -x $clang ]]; then
    build_run "clang: C-Programm" "hallo 1" "$clang" "$WORK/hello.c" || true
    # clang++ is not part of the acceptance (index.md, research.md 6): a failure is only a warning.
    if "$PREFIX/opt/llvm/bin/clang++" -o "$WORK/clang++.bin" "$WORK/hello.cpp" >"$WORK/clang++.log" 2>&1 &&
        [[ $("$WORK/clang++.bin" 2>&1) == "hallo c++" ]]; then
        pass "clang++: C++-Programm"
    else
        warn "clang++: C++-Programm scheitert (kein Teil der Abnahme): $(grep -m1 'error' "$WORK/clang++.log" || echo 'siehe clang++ -v')"
    fi
else
    fail "clang: $clang fehlt; installieren: brew install llvm"
fi

exit "$FAILED"

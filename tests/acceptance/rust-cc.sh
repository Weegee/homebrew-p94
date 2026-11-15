#!/usr/bin/env bash
# Acceptance test (AK-12): a Rust crate with a cc build script builds and runs.
# Needs network access to crates.io. One line per check: "✓ ..." passed, "✗ ..." failed.
set -euo pipefail

PROG=${0##*/}
SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
PREFIX=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}
CARGO=$PREFIX/bin/cargo

[[ -x $CARGO ]] || {
    printf '%s: Fehler: %s fehlt; erst bin/p94-brew-bootstrap ausführen.\n' "$PROG" "$CARGO" >&2
    exit 1
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/p94-rust-cc.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
cp -r "$SCRIPT_DIR/../fixtures/rust-cc" "$WORK/rust-cc"

export PATH=$PREFIX/bin:$PATH
got=$(CARGO_HOME="$WORK/cargo" CARGO_TARGET_DIR="$WORK/target" "$CARGO" run --quiet \
    --manifest-path "$WORK/rust-cc/Cargo.toml" 2>"$WORK/cargo.log" || true)
if [[ $got == "hallo 42" ]]; then
    printf '✓ Rust-Crate mit cc-Build-Skript\n'
else
    printf '✗ cargo run gibt „%s“ statt „hallo 42“\n' "$got"
    tail -n 8 "$WORK/cargo.log" | sed 's/^/  /'
    exit 1
fi

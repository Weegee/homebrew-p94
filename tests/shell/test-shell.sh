#!/usr/bin/env bash
# Tests the shell integration against the real Homebrew: interactive bash and fish, environment.d.
# One line per check: "✓ ..." passed, "✗ ..." failed, "– ..." not checked. Exit 1 on any failure.
set -euo pipefail

PROG=${0##*/}
PREFIX=/home/linuxbrew/.linuxbrew
FAILED=0
# Sha256 of ~/.bash_profile before the integration (index.md AK-5); override for other machines.
BASH_PROFILE_SHA256=${BASH_PROFILE_SHA256:-f4502974771f5c026412c0bb598ae438b2f9f3586f4c72527dd426a648052c74}

pass() { printf '✓ %s\n' "$*"; }
fail() {
    printf '✗ %s\n' "$*"
    FAILED=1
}
skip() { printf '– %s\n' "$*"; }

[[ -x $PREFIX/bin/brew ]] || {
    printf '%s: Fehler: Homebrew fehlt unter %s; erst bin/p94-brew-bootstrap ausführen.\n' "$PROG" "$PREFIX" >&2
    exit 1
}

# run_pty CMD...: run in a pseudo terminal like an ssh login, without carriage returns.
run_pty() {
    script -qec "$*" /dev/null 2>&1 | tr -d '\r'
}

# --- bash ---------------------------------------------------------------------------------------
# shellcheck disable=SC2016 # the inner shell expands the variables
out=$(run_pty 'bash -lic "command -v brew; printf \"PATH=%s\\n\" \"\$PATH\"; complete -p brew >/dev/null && echo brew-completion"') || true
brew_path=$(printf '%s\n' "$out" | grep -m1 '/brew$' || true)
path_line=$(printf '%s\n' "$out" | grep -m1 '^PATH=' || true)
path_value=${path_line#PATH=}

if [[ $brew_path == "$PREFIX/bin/brew" ]]; then
    pass "B1 bash: brew kommt aus $PREFIX/bin"
else
    fail "B1 bash: brew nicht aus dem Prefix gefunden (gefunden: ${brew_path:-nichts})"
fi
if [[ $path_value == "$HOME/.local/bin:$PREFIX/bin:$PREFIX/sbin"* ]]; then
    pass "B1 bash: PATH beginnt mit ~/.local/bin, Homebrew bin, sbin"
else
    fail "B1 bash: PATH beginnt anders: ${path_value:0:120}"
fi
if grep -q '^brew-completion$' <<<"$out"; then
    pass "B1 bash: Vervollständigung für brew geladen"
else
    fail "B1 bash: keine Vervollständigung für brew (complete -p brew)"
fi

if [[ -d $PREFIX/opt/node@24/bin ]]; then
    IFS=: read -r -a parts <<<"$path_value"
    if [[ ${parts[3]:-} == "$PREFIX/opt/node@24/bin" ]]; then
        pass "B2 bash: node@24 steht an vierter Stelle im PATH"
    else
        fail "B2 bash: vierter PATH-Eintrag ist ${parts[3]:-leer}, erwartet $PREFIX/opt/node@24/bin"
    fi
else
    skip "B2 node@24 noch nicht installiert (Plan 007)"
fi

count=$(printf '%s' "$path_value" | tr ':' '\n' | grep -cx "$PREFIX/bin" || true)
if [[ $count == 1 ]]; then
    pass "B3 bash: $PREFIX/bin kommt genau einmal im PATH vor"
else
    fail "B3 bash: $PREFIX/bin kommt ${count}-mal im PATH vor"
fi

# --- fish ---------------------------------------------------------------------------------------
# shellcheck disable=SC2016 # the inner shell expands the variables
out=$(run_pty 'fish -lic "command -v brew; echo PATH=(string join : \$PATH); printf \"COMP=%s\\n\" \$fish_complete_path"') || true
brew_path=$(printf '%s\n' "$out" | grep -m1 '/brew$' || true)
path_line=$(printf '%s\n' "$out" | grep -m1 '^PATH=' || true)
path_value=${path_line#PATH=}
if [[ $brew_path == "$PREFIX/bin/brew" ]]; then
    pass "F1 fish: brew kommt aus $PREFIX/bin"
else
    fail "F1 fish: brew nicht aus dem Prefix gefunden (gefunden: ${brew_path:-nichts})"
fi
if [[ $path_value == "$HOME/.local/bin:$PREFIX/bin"* ]]; then
    pass "F1 fish: PATH beginnt mit ~/.local/bin und Homebrew bin"
else
    fail "F1 fish: PATH beginnt anders: ${path_value:0:120}"
fi
if [[ -d $PREFIX/share/fish/vendor_completions.d ]]; then
    comp_list=$(printf '%s\n' "$out" | sed -n 's/^COMP=//p')
    first_after=$(printf '%s\n' "$comp_list" | grep -A1 -Fx "$HOME/.config/fish/completions" | sed -n 2p || true)
    if [[ $first_after == "$PREFIX/share/fish/vendor_completions.d" ]]; then
        pass "F1 fish: vendor_completions.d steht direkt hinter ~/.config/fish/completions"
    else
        fail "F1 fish: hinter ~/.config/fish/completions steht ${first_after:-nichts}"
    fi
else
    skip "F1 fish: $PREFIX/share/fish/vendor_completions.d fehlt noch (keine Formel mit fish-Vervollständigung)"
fi

# --- environment.d and login files ---------------------------------------------------------------
gen=/usr/lib/systemd/user-environment-generators/30-systemd-environment-d-generator
want="PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:$PREFIX/bin:$PREFIX/sbin:$PREFIX/opt/node@24/bin"
got=$(env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin "$gen" | grep '^PATH=' || true)
if [[ $got == "$want" ]]; then
    pass "E1 environment.d: Homebrew steht hinten im PATH der Sitzung"
else
    fail "E1 environment.d: PATH ist $got, erwartet $want"
fi

if [[ $(sha256sum "$HOME/.bash_profile" | cut -d' ' -f1) == "$BASH_PROFILE_SHA256" ]] &&
    [[ -z $(chezmoi diff "$HOME/.bash_profile" 2>/dev/null) ]]; then
    pass "E2 ~/.bash_profile ist unverändert und stimmt mit chezmoi überein"
else
    fail "E2 ~/.bash_profile weicht vom Stand vor der Einbindung ab"
fi

skip "S1 nicht geprüft: echte Sitzung von Plasma und Game Mode; nach dem nächsten Neustart: systemctl --user show-environment | grep ^PATH="

exit "$FAILED"

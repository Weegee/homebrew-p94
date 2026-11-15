#!/usr/bin/env bash
# End-to-end test of the formula path with the real Homebrew and a throw-away tap p94test/e2e:
# sync, install, link, shell, upgrade, remove. The test formula is the fixture tests/fixtures/p94-hello.
# One line per step: "✓ ..." passed, "✗ ..." failed (the test stops there), "– ..." not checked.
# Everything it creates is removed again, also after a failure. Exit 1 on any failure.
set -euo pipefail

PROG=${0##*/}
SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
REPO=$(dirname "$(dirname "$SCRIPT_DIR")")
PREFIX=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}
BREW=$PREFIX/bin/brew
TAP=p94test/e2e
FORMULA=p94-hello
UNIT_LINK=$HOME/.config/systemd/user/p94-hello.service
CONF_LINK=$HOME/.config/p94-hello/hello.conf
GIT_ID=(-c user.name=p94-e2e -c user.email=p94-e2e@example.org)
LQ='„' # German quotes, kept in variables because shellcheck flags them in strings
RQ='“'

pass() { printf '✓ %s\n' "$*"; }
skip() { printf '– %s\n' "$*"; }
fail() {
    printf '✗ %s\n' "$*"
    exit 1
}

[[ -x $BREW ]] || {
    printf '%s: Fehler: Homebrew fehlt unter %s; erst bin/p94-brew-bootstrap ausführen.\n' "$PROG" "$PREFIX" >&2
    exit 1
}
if "$BREW" tap | grep -qx "$TAP"; then
    printf '%s: Fehler: Tap %s existiert schon; entfernen mit: brew untap %s\n' "$PROG" "$TAP" "$TAP" >&2
    exit 1
fi
if [[ -n $("$BREW" list --versions "$FORMULA" 2>/dev/null) ]]; then
    printf '%s: Fehler: %s ist schon installiert; erst brew uninstall %s\n' "$PROG" "$FORMULA" "$FORMULA" >&2
    exit 1
fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/p94-e2e.XXXXXX")
SRC=$TMP/p94-hello
# Homebrew keeps the git clone of a formula by its name, not by its URL. The test repository is new on
# every run but reuses the tag, so a stale clone would report "tag should be ... but is actually ...".
GIT_CACHE=$("$BREW" --cache)/$FORMULA--git

# shellcheck disable=SC2329 # called through the EXIT trap
cleanup() {
    "$BREW" uninstall --force "$TAP/$FORMULA" >/dev/null 2>&1 || true
    if "$BREW" tap 2>/dev/null | grep -qx "$TAP"; then
        "$BREW" untap "$TAP" >/dev/null 2>&1 || true
        "$BREW" untrust --tap "$TAP" >/dev/null 2>&1 || true
    fi
    "$BREW" p94-link >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    rm -rf -- "$TMP" "$GIT_CACHE" "${XDG_CACHE_HOME:-$HOME/.cache}/p94-sync/$FORMULA.git"
}
trap cleanup EXIT
rm -rf -- "$GIT_CACHE"

# run_pty CMD: run in a pseudo terminal like an ssh login, without carriage returns.
run_pty() {
    script -qec "$*" /dev/null 2>&1 | tr -d '\r'
}

# 1. source repository with a tag
cp -r "$REPO/tests/fixtures/p94-hello" "$SRC"
git -C "$SRC" init -q -b main
git -C "$SRC" add -A
git -C "$SRC" "${GIT_ID[@]}" commit -q -m "p94-hello 20261104.01"
git -C "$SRC" tag v20261104.01
pass "1 Quell-Repository mit Tag v20261104.01"

# 2. throw-away tap with a source list
"$BREW" tap-new "$TAP" >"$TMP/tap-new.log" 2>&1 || fail "2 brew tap-new $TAP scheitert: $(tail -n 1 "$TMP/tap-new.log")"
TAP_DIR=$("$BREW" --repository "$TAP")
printf '[[source]]\nname = "p94-hello"\nurl = "%s"\n' "$SRC" >"$TAP_DIR/p94-sync.toml"
git -C "$TAP_DIR" add p94-sync.toml
git -C "$TAP_DIR" "${GIT_ID[@]}" commit -q -m "p94-sync.toml"
"$BREW" trust --tap "$TAP" >/dev/null 2>&1 || fail "2 brew trust --tap $TAP scheitert"
pass "2 Tap $TAP mit p94-sync.toml"

# 3. sync
"$BREW" p94-sync --tap "$TAP" --no-upgrade >"$TMP/sync1.log" 2>"$TMP/sync1.err" ||
    fail "3 brew p94-sync scheitert: $(tail -n 3 "$TMP/sync1.err" | tr '\n' ' ')"
grep -Eq "^p94-hello +p94-hello +.* neu$" "$TMP/sync1.log" ||
    fail "3 Tabelle ohne Zeile ${LQ}neu${RQ}: $(tr '\n' '|' <"$TMP/sync1.log")"
grep -q 'tag:      "v20261104.01"' "$TAP_DIR/Formula/$FORMULA.rb" ||
    fail "3 Formel enthält den Tag v20261104.01 nicht"
grep -Eq 'using: +:git' "$TAP_DIR/Formula/$FORMULA.rb" || fail "3 Formel enthält using: :git nicht"
pass "3 brew p94-sync: Formel neu, Tag v20261104.01, using: :git"

# 4. install
"$BREW" install "$TAP/$FORMULA" >"$TMP/install.log" 2>&1 ||
    fail "4 brew install scheitert: $(tail -n 3 "$TMP/install.log" | tr '\n' ' ')"
got=$("$PREFIX/bin/p94-hello" --version 2>&1 || true)
[[ $got == "p94-hello 20261104.01" ]] || fail "4 p94-hello --version gibt ${LQ}${got}${RQ}"
pass "4 brew install: p94-hello --version gibt ${LQ}${got}${RQ}"

# 5. link, unit run
"$BREW" p94-link "$FORMULA" >"$TMP/link.log" 2>&1 ||
    fail "5 brew p94-link scheitert: $(tail -n 3 "$TMP/link.log" | tr '\n' ' ')"
want_unit=$PREFIX/opt/p94-hello/lib/systemd/user/p94-hello.service
[[ $(readlink "$UNIT_LINK" || true) == "$want_unit" ]] || fail "5 $UNIT_LINK zeigt nicht auf $want_unit"
[[ -L $CONF_LINK ]] || fail "5 $CONF_LINK ist kein Link"
if systemctl --user is-system-running >/dev/null 2>&1; then
    systemctl --user start p94-hello.service || fail "5 systemctl --user start p94-hello.service scheitert"
    result=$(systemctl --user show -p Result --value p94-hello.service)
    [[ $result == success ]] || fail "5 Unit-Ergebnis ${LQ}${result}${RQ} statt ${LQ}success${RQ}"
    pass "5 brew p94-link: Unit und Konfiguration verlinkt, Unit lief mit Ergebnis success"
else
    pass "5 brew p94-link: Unit und Konfiguration verlinkt"
    skip "5 Unit nicht gestartet: kein systemd-User-Manager erreichbar"
fi

# 6. shell: hook and completion from the formula
out=$(run_pty 'bash -lic "type -t p94_hello_hook; _comp_load p94-hello; complete -p p94-hello"') || true
grep -qx 'function' <<<"$out" || fail "6 bash: p94_hello_hook ist keine Funktion (Ausgabe: $(tr '\n' '|' <<<"$out"))"
grep -q 'complete -W .*p94-hello' <<<"$out" || fail "6 bash: keine Vervollständigung für p94-hello"
pass "6 bash: Hook-Funktion und Vervollständigung aus der Formel geladen"
out=$(run_pty 'fish -lic "functions -q p94_hello_hook; and echo fish-hook; complete -C\"p94-hello --\""') || true
grep -q 'fish-hook' <<<"$out" || fail "6 fish: p94_hello_hook fehlt (Ausgabe: $(tr '\n' '|' <<<"$out"))"
grep -q -- '--version' <<<"$out" || fail "6 fish: keine Vervollständigung --version"
pass "6 fish: Hook-Funktion und Vervollständigung aus der Formel geladen"

# 7. upgrade
sed -i 's/^20261104.01$/20261104.02/' "$SRC/VERSION"
sed -i 's/^VERSION = "20261104.01"$/VERSION = "20261104.02"/' "$SRC/bin/p94-hello"
git -C "$SRC" add -A
git -C "$SRC" "${GIT_ID[@]}" commit -q -m "p94-hello 20261104.02"
git -C "$SRC" tag v20261104.02
"$BREW" p94-sync --tap "$TAP" >"$TMP/sync2.log" 2>"$TMP/sync2.err" ||
    fail "7 brew p94-sync scheitert: $(tail -n 3 "$TMP/sync2.err" | tr '\n' ' ')"
grep -Eq "^p94-hello +p94-hello +.* aktualisiert$" "$TMP/sync2.log" ||
    fail "7 Tabelle ohne Zeile ${LQ}aktualisiert${RQ}: $(tr '\n' '|' <"$TMP/sync2.log")"
got=$("$PREFIX/bin/p94-hello" --version 2>&1 || true)
[[ $got == "p94-hello 20261104.02" ]] || fail "7 nach dem Upgrade gibt p94-hello --version ${LQ}${got}${RQ}"
[[ -e $UNIT_LINK ]] || fail "7 der Unit-Link löst nach dem Upgrade nicht mehr auf"
pass "7 brew p94-sync: aktualisiert und upgegradet, p94-hello --version gibt ${LQ}${got}${RQ}, Unit-Link gültig"

# 8. remove
"$BREW" uninstall "$TAP/$FORMULA" >"$TMP/uninstall.log" 2>&1 ||
    fail "8 brew uninstall scheitert: $(tail -n 3 "$TMP/uninstall.log" | tr '\n' ' ')"
"$BREW" p94-link >"$TMP/link2.log" 2>&1 || fail "8 brew p94-link scheitert: $(tail -n 3 "$TMP/link2.log" | tr '\n' ' ')"
removed=$(grep -c 'entfernt' "$TMP/link2.log" || true)
[[ $removed -ge 2 ]] || fail "8 brew p94-link meldet $removed statt 2 Zeilen ${LQ}entfernt${RQ}"
if [[ -e $UNIT_LINK || -L $UNIT_LINK || -e $HOME/.config/p94-hello ]]; then
    fail "8 Unit-Link oder ~/.config/p94-hello sind noch da"
fi
pass "8 brew uninstall und brew p94-link: beide Links entfernt"

# 9. clean up
"$BREW" untap "$TAP" >/dev/null 2>&1 || fail "9 brew untap $TAP scheitert"
"$BREW" untrust --tap "$TAP" >/dev/null 2>&1 || fail "9 brew untrust --tap $TAP scheitert"
if "$BREW" tap | grep -qx "$TAP"; then fail "9 Tap $TAP ist noch eingebunden"; fi
pass "9 Tap $TAP entfernt"

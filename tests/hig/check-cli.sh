#!/usr/bin/env bash
# Checks the output of every command against the test recipes of the p94-hig text part
# (references/text/checkliste.md). One line per command and rule: "✓ ..." passed, "✗ ..." failed.
# Exit 1 if any rule failed. The commands run with arguments that change nothing.
#
# Not applicable, with reason:
#   HIL-3, KAN-5  the commands have no required arguments; without arguments they run their default.
#   MAS-1, MAS-3  no machine format is offered (non-goal).
#   TUI-13        no full-screen interface.
set -uo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
REPO=$(dirname "$(dirname "$SCRIPT_DIR")")
export PATH=${P94_BREW_PREFIX:-/home/linuxbrew/.linuxbrew}/bin:$PATH

# Colour codes as cat -v shows them, and the symbols that need a Unicode terminal.
SGR='\^\[\[([0-9]*;)*(3[0-9]|4[0-9]|9[0-7]|10[0-7])(;[0-9]*)*m'
LQ='„' # German quotes in variables: shellcheck flags them inside strings
RQ='“'
SYM='[✓✗→…•●○⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]'

TMP=$(mktemp -d "${TMPDIR:-/tmp}/p94-hig.XXXXXX")
trap 'rm -rf -- "$TMP"' EXIT
total=0
failed=0

report() { # report ID PROG DESCRIPTION STATUS(0 = passed)
    total=$((total + 1))
    if [[ $4 -eq 0 ]]; then
        printf '✓ %s %s: %s\n' "$1" "$2" "$3"
    else
        failed=$((failed + 1))
        printf '✗ %s %s: %s\n' "$1" "$2" "$3"
    fi
}

# check_cmd NAME ARGS...: all recipes that fit a command. ARGS change nothing.
# The second word of NAME is the executable below the repository.
check_cmd() {
    local name=$1 exe=$2
    shift 2
    local args=("$@") prog=("$REPO/$exe")
    local out=$TMP/out err=$TMP/err rc

    # HIL-1: --help prints to stdout, exits 0, writes nothing to stderr
    "${prog[@]}" --help >"$out" 2>"$err"
    rc=$?
    s=1
    if [[ $rc -eq 0 && -s $out && ! -s $err ]]; then s=0; fi
    report HIL-1 "$name" "--help gibt Exit $rc, stdout $(wc -l <"$out") Zeilen, stderr $(wc -l <"$err") Zeilen" "$s"

    # HIL-2: --version prints name and version, exit 0
    version=$(<"$REPO/VERSION")
    got=$("${prog[@]}" --version 2>&1)
    rc=$?
    s=1
    if [[ $rc -eq 0 && $got == *"$version"* ]]; then s=0; fi
    report HIL-2 "$name" "--version gibt Exit $rc und ${LQ}${got}${RQ}" "$s"

    # KAN-3: unknown option gives an error on stderr, a pointer to --help and exit 2
    "${prog[@]}" --gibts-nicht >"$out" 2>"$err"
    rc=$?
    s=1
    if [[ $rc -eq 2 && ! -s $out ]] && grep -q -- '--help' "$err"; then s=0; fi
    report KAN-3 "$name" "unbekannte Option gibt Exit $rc, stdout leer, Verweis auf --help" "$s"

    # The remaining recipes run the typical call
    "${prog[@]}" "${args[@]}" >"$out" 2>"$err" </dev/null
    rc=$?
    s=1
    if [[ $rc -eq 0 ]]; then s=0; fi
    report ARGS "$name" "${args[*]} gibt Exit $rc" "$s"

    # KAN-1: no message on stdout
    ! grep -Eq '^[a-z0-9-]+: (Fehler|Warnung)' "$out"
    report KAN-1 "$name" "stdout enthält keine Fehler- oder Warnmeldung" "$s"

    # KAN-4: stdout ends with a newline
    if [[ -s $out ]]; then
        s=1
        if [[ $(tail -c1 "$out" | od -An -c | tr -d ' ') == '\n' ]]; then s=0; fi
        report KAN-4 "$name" "stdout endet mit Zeilenumbruch" "$s"
    else
        report KAN-4 "$name" "stdout ist leer, alles geht nach stderr" 0
    fi

    # MOD-2, FAR-3, FAR-7: without a terminal no escape sequence
    n=$("${prog[@]}" "${args[@]}" 2>&1 </dev/null | grep -c $'\e')
    s=1
    if [[ $n -eq 0 ]]; then s=0; fi
    report MOD-2 "$name" "ohne Terminal $n Escape-Zeichen" "$s"

    # FOR-4, BEW-1: without a terminal no carriage return
    n=$("${prog[@]}" "${args[@]}" 2>&1 </dev/null | grep -c $'\r')
    s=1
    if [[ $n -eq 0 ]]; then s=0; fi
    report FOR-4 "$name" "ohne Terminal $n Wagenrückläufe" "$s"

    # FAR-3: NO_COLOR in a terminal gives no colour code
    n=$(NO_COLOR=1 script -qec "${prog[*]} ${args[*]}" /dev/null </dev/null | cat -v | grep -cE "$SGR")
    s=1
    if [[ $n -eq 0 ]]; then s=0; fi
    report FAR-3 "$name" "mit NO_COLOR im Terminal $n Farbcodes" "$s"

    # MOD-3: TERM=dumb in a terminal gives no escape sequence
    n=$(TERM=dumb script -qec "${prog[*]} ${args[*]}" /dev/null </dev/null | grep -c $'\e')
    s=1
    if [[ $n -eq 0 ]]; then s=0; fi
    report MOD-3 "$name" "mit TERM=dumb im Terminal $n Escape-Zeichen" "$s"

    # TYP-6: with LC_ALL=C only ASCII symbols
    n=$(LC_ALL=C "${prog[@]}" "${args[@]}" 2>&1 </dev/null | grep -c "$SYM")
    s=1
    if [[ $n -eq 0 ]]; then s=0; fi
    report TYP-6 "$name" "mit LC_ALL=C $n Sonderzeichen" "$s"

    # MOD-4, TYP-2: --help fits 60 columns
    n=$(COLUMNS=60 "${prog[@]}" --help 2>&1 | LC_ALL=C.UTF-8 awk 'length > 60' | wc -l)
    s=1
    if [[ $n -eq 0 ]]; then s=0; fi
    report MOD-4 "$name" "bei 60 Spalten $n Hilfezeilen zu breit" "$s"

    # EIN-1: stdin closed, no prompt: the call above already ran with </dev/null and exit 0
    report EIN-1 "$name" "ohne Eingabe keine Rückfrage (Exit $rc mit </dev/null)" "$((rc != 0))"
}

# run_signalled SIGNAL CMD ARGS...: starts CMD, sends SIGNAL as soon as CMD runs a child process
# (the call is then in the middle of its work, not at its start or end), at the latest after
# 10 s, and sets rc to the exit status. No fixed delay: a late start under load or a call that ends
# early does not shift the point of the signal.
run_signalled() {
    local sig=$1 pid i
    shift
    set -m # own process group and default signal handling for the background call
    "$@" >/dev/null 2>&1 </dev/null &
    pid=$!
    set +m
    for ((i = 0; i < 500; i++)); do # 500 x 20 ms: at least 10 s
        kill -0 "$pid" 2>/dev/null || break
        pgrep -P "$pid" >/dev/null 2>&1 && break
        sleep 0.02
    done
    kill -s "$sig" "$pid" 2>/dev/null
    wait "$pid"
    rc=$?
}

# check_signals NAME ARGS...: SIG-1 and SIG-4 with a call that runs a few seconds
check_signals() {
    local name=$1 exe=$2
    shift 2
    local rc
    run_signalled INT "$REPO/$exe" "$@"
    s=1
    if [[ $rc -eq 130 ]]; then s=0; fi
    report SIG-1 "$name" "Ctrl+C beendet mit Exit $rc (erwartet 130)" "$s"
    run_signalled TERM "$REPO/$exe" "$@"
    s=1
    if [[ $rc -eq 143 ]]; then s=0; fi
    report SIG-4 "$name" "SIGTERM beendet mit Exit $rc (erwartet 143)" "$s"
}

check_cmd p94-brew-bootstrap bin/p94-brew-bootstrap --dry-run
check_cmd "brew p94-sync" cmd/brew-p94-sync --dry-run
check_signals "brew p94-sync" cmd/brew-p94-sync --dry-run
check_cmd "brew p94-link" cmd/brew-p94-link --list
check_cmd "brew p94-toolchain" cmd/brew-p94-toolchain check
check_cmd p94-brew-migrate bin/p94-brew-migrate --dry-run
check_cmd p94-formula-try bin/p94-formula-try --help

if [[ $failed -eq 0 ]]; then
    printf '✓ Prüfung der Ausgaben: %d von %d\n' "$total" "$total"
else
    printf '✗ Prüfung der Ausgaben: %d von %d scheitern\n' "$failed" "$total"
    exit 1
fi

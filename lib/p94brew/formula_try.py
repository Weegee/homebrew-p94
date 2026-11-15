"""``p94-formula-try``: check formula templates of a source project in a throw-away tap.

The templates under ``packaging/homebrew/`` are taken from a commit of the project (no tag needed),
pointed at the local repository and run through ``brew style``, ``audit``, ``install
--build-from-source``, ``test`` and ``p94-link --dry-run``. Tap, formulae and trust are removed
afterwards, also after a failure, unless ``--keep`` is given.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from . import __version__, cli, env, formula_edit
from .cli import Fehler, Output, plural
from .runner import Runner

PROG = "p94-formula-try"
TRY_TAP = "p94try/try"
TEMPLATE_DIR = "packaging/homebrew"


def _git(runner: Runner, repo: Path, *args: str) -> str:
    return runner.run(["git", "-C", str(repo), *args], check=True).stdout.strip()


def resolve_commit(repo: Path, rev: str, runner: Runner) -> str:
    result = runner.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{rev}^{{commit}}"])
    sha = result.stdout.strip()
    if result.returncode != 0 or not sha:
        raise Fehler(f"Commit {rev} in {repo} nicht gefunden; Name oder Hash prüfen")
    return sha


def read_version(repo: Path, rev: str, runner: Runner) -> str:
    result = runner.run(["git", "-C", str(repo), "show", f"{rev}:VERSION"])
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        raise Fehler(
            f"VERSION fehlt in {repo} (Commit {rev[:7]}); die Datei VERSION anlegen und committen"
        )
    return version


def list_templates(repo: Path, rev: str, runner: Runner) -> list[str]:
    result = runner.run(["git", "-C", str(repo), "ls-tree", "--name-only", rev, f"{TEMPLATE_DIR}/"])
    if result.returncode != 0:
        return []
    return sorted(
        Path(line.strip()).stem for line in result.stdout.splitlines() if line.endswith(".rb")
    )


def read_template(repo: Path, rev: str, formula: str, runner: Runner) -> str:
    return runner.run(
        ["git", "-C", str(repo), "show", f"{rev}:{TEMPLATE_DIR}/{formula}.rb"], check=True
    ).stdout


def _installed_tap(brew: str, formula: str, runner: Runner) -> str | None:
    """The tap an installed formula of this name comes from; ``None`` if it is not installed."""
    listed = runner.run([brew, "list", "--formula", "--versions", formula])
    if listed.returncode != 0 or not listed.stdout.strip():
        return None
    info = runner.run([brew, "info", "--json=v2", "--formula", formula])
    try:
        return json.loads(info.stdout)["formulae"][0].get("tap") or "unbekannt"
    except (ValueError, KeyError, IndexError):
        return "unbekannt"


def _tail(text: str, lines: int = 8) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def run_try(
    repo: Path,
    formulae: Sequence[str],
    rev: str | None,
    keep: bool,
    runner: Runner,
    output: Output,
    brew: str,
) -> int:
    if not (repo / ".git").exists():
        raise Fehler(f"{repo} ist kein Git-Repository")
    commit = resolve_commit(repo, rev or "HEAD", runner)
    version = read_version(repo, commit, runner)
    available = list_templates(repo, commit, runner)
    if not available:
        raise Fehler(f"keine Vorlage unter {TEMPLATE_DIR}/ in {repo} (Commit {commit[:7]})")
    wanted = list(formulae) or available
    for name in wanted:
        if name not in available:
            raise Fehler(
                f"Vorlage {name}.rb fehlt unter {TEMPLATE_DIR}/ (vorhanden: {', '.join(available)})"
            )
    for name in wanted:
        tap = _installed_tap(brew, name, runner)
        if tap is not None:
            raise Fehler(f"{name} ist schon aus {tap} installiert; erst brew uninstall {name}")
    tapped = runner.run([brew, "tap"]).stdout.split()
    if TRY_TAP in tapped:
        raise Fehler(f"Tap {TRY_TAP} existiert schon; entfernen mit: brew untap {TRY_TAP}")

    failed = 0
    created = False
    installed: list[str] = []
    try:
        runner.run([brew, "tap-new", "--no-git", TRY_TAP], check=True)
        created = True
        runner.run([brew, "trust", "--tap", TRY_TAP], check=True)
        tap_path = Path(runner.run([brew, "--repository", TRY_TAP], check=True).stdout.strip())
        (tap_path / "Formula").mkdir(parents=True, exist_ok=True)
        for name in wanted:
            text = formula_edit.set_try_source(
                read_template(repo, commit, name, runner), str(repo), commit, version
            )
            (tap_path / "Formula" / f"{name}.rb").write_text(text, encoding="utf-8")
        output.info(
            f"Prüfe {plural(len(wanted), 'Formel', 'Formeln')} aus {repo} (Commit {commit[:7]})"
        )
        for name in wanted:
            full = f"{TRY_TAP}/{name}"
            steps = [
                ("brew style", [brew, "style", "--formula", full]),
                ("brew audit", [brew, "audit", "--formula", full]),
                (
                    "brew install --build-from-source",
                    [brew, "install", "--build-from-source", full],
                ),
                ("brew test", [brew, "test", full]),
                ("brew p94-link --dry-run", [brew, "p94-link", "--dry-run", name]),
            ]
            for label, command in steps:
                output.info(f"{name}: {label} ...")
                result = runner.run(command)
                if label.startswith("brew install"):
                    installed.append(name)
                ok = result.returncode == 0
                output.check(ok, f"{name}: {label}")
                if not ok:
                    failed += 1
                    for line in _tail(result.stdout + "\n" + result.stderr).splitlines():
                        output.info(f"  {line}")
                    break
    finally:
        if keep:
            output.info(f"Wegwerf-Tap {TRY_TAP} bleibt; entfernen mit: brew untap {TRY_TAP}")
        elif created:
            for name in installed:
                runner.run([brew, "uninstall", "--force", f"{TRY_TAP}/{name}"])
            runner.run([brew, "untap", TRY_TAP])
            runner.run([brew, "untrust", "--tap", TRY_TAP])
    output.out.flush()  # keep the summary after the result lines on one terminal
    if failed:
        print(
            f"{output.fail_sym} {plural(failed, 'Prüfung', 'Prüfungen')} fehlgeschlagen",
            file=output.err,
        )
        return cli.EXIT_ERROR
    output.note("Alle Prüfungen bestanden")
    return cli.EXIT_OK


def _build_parser():
    parser = cli.make_parser(
        PROG,
        "Prüft Formelvorlagen eines Projekts (packaging/homebrew/*.rb) in einem Wegwerf-Tap.",
        epilog=(
            "Beispiele:\n"
            "  p94-formula-try ~/Projects/Linux/claude-tools\n"
            "  p94-formula-try --rev v20261104.01 ~/Projects/Linux/claude-tools claude-tools\n\n"
            "REPO ist der Ordner des Quellprojekts; die Vorlagen kommen aus einem Commit,\n"
            "nicht aus dem Arbeitsordner.\n"
            "Exit-Status: 0 alles bestanden, 1 Prüfung fehlgeschlagen oder Fehler,\n"
            "2 falscher Aufruf."
        ),
    )
    parser.usage = f"{PROG} [OPTIONEN] REPO [FORMEL ...]"
    args = parser.add_argument_group("Argumente")
    args.add_argument("repo", metavar="REPO", help="Ordner des Quellprojekts")
    args.add_argument(
        "formulae", nargs="*", metavar="FORMEL", help="nur diese Vorlagen (Vorgabe: alle)"
    )
    opts = parser.add_argument_group("Aktionen")
    opts.add_argument("--rev", metavar="REV", help="Commit statt HEAD")
    opts.add_argument("--keep", action="store_true", help="Wegwerf-Tap und Formeln behalten")
    cli.add_common_options(parser, __version__)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    env.restore_user_env()
    args = _build_parser().parse_args(argv)
    output = Output(PROG, color=args.color, quiet=args.quiet, verbose=args.verbose)
    runner = Runner(output=output)
    repo = Path(args.repo).expanduser().resolve()
    return run_try(repo, args.formulae, args.rev, args.keep, runner, output, str(env.brew_bin()))


def main_entry() -> NoReturn:
    cli.run_main(PROG, main)


if __name__ == "__main__":
    main_entry()
    sys.exit(0)

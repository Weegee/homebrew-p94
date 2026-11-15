"""``brew p94-sync``: generate the SteamOS mirror formulae and, if configured, source formulae.

The tap is a clone of the project repository. Commits made in the clone would run away from the
project (``brew update`` resets it), so the formulae are committed in the project repository and
the tap fast-forwards afterwards. The project is ``$P94_TAP_PROJEKT``, else the local path in the
tap's ``origin``, else ``~/Projects/Linux/homebrew-p94``. Pushing stays manual. The source formulae
of the tools (claude-tools and others) are written by the CI of Weegee/p94 after each release, so
``p94-sync.toml`` has no ``[[source]]`` entries by default; the code still reads them.
"""

from __future__ import annotations

import fcntl
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from . import __version__, cli, env, formula_edit, gitsrc, steamos
from .cli import Fehler, Output, plural
from .runner import Runner

PROG = "brew p94-sync"
DEFAULT_TAP = "weegee/p94"
PROJECT_ENV = "P94_TAP_PROJEKT"
PROJECT_DEFAULT = "Projects/Linux/homebrew-p94"
SOURCE_KEYS = {"name", "url", "formulae"}


@dataclass
class Source:
    name: str
    url: str
    formulae: list[str] | None = None


def load_config(path: Path) -> tuple[list[Source], list[str]]:
    """Read ``p94-sync.toml``: the source projects and the SteamOS mirror lists."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise Fehler(f"{path.name} unlesbar: {exc}") from exc
    unknown = set(data) - {"source", "steamos"}
    if unknown:
        raise Fehler(f"{path.name}: unbekannter Schlüssel '{sorted(unknown)[0]}'")
    sources: list[Source] = []
    for item in data.get("source", []):
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise Fehler(f"{path.name}: [[source]] ohne name")
        for key in item:
            if key not in SOURCE_KEYS:
                raise Fehler(f"{path.name}: unbekannter Schlüssel '{key}' in [[source]] {name}")
        formulae = item.get("formulae")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise Fehler(f"{path.name}: [[source]] {name} ohne url")
        sources.append(Source(name, url, formulae))
    steamos = data.get("steamos", {})
    for key in steamos:
        if key != "lists":
            raise Fehler(f"{path.name}: unbekannter Schlüssel '{key}' in [steamos]")
    return sources, list(steamos.get("lists", []))


@dataclass
class TapInfo:
    name: str
    path: Path
    source_repo: Path
    branch: str


def _git(runner: Runner, repo: Path, *args: str, check: bool = True) -> str:
    return runner.run(["git", "-C", str(repo), *args], check=check).stdout.strip()


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _project_dir(tap: str, clone: Path, runner: Runner) -> Path:
    """The repository that gets the commits: env, local origin or default dir."""
    configured = os.environ.get(PROJECT_ENV)
    if configured:
        project = Path(configured).expanduser()
        if not _is_git_repo(project):
            raise Fehler(
                f"{PROJECT_ENV}={configured} ist kein Git-Repository; "
                f"Pfad des Projektordners setzen: export {PROJECT_ENV}=PFAD"
            )
        return project
    origin = runner.run(["git", "-C", str(clone), "remote", "get-url", "origin"])
    url = origin.stdout.strip() if origin.returncode == 0 else ""
    if not url:
        return clone
    if url.startswith("/"):
        return Path(url)
    default = env.home() / PROJECT_DEFAULT
    if _is_git_repo(default):
        return default
    raise Fehler(
        f"kein Projektordner für den Tap {tap} gefunden: origin ist {url}, und Commits im "
        f"Klon gingen bei brew update verloren; Projekt klonen nach {default} oder "
        f"Pfad setzen: export {PROJECT_ENV}=PFAD"
    )


def tap_info(tap: str, runner: Runner) -> TapInfo:
    """Locate the tap clone and the repository its commits belong to."""
    result = runner.run(["brew", "--repository", tap], check=True)
    path = Path(result.stdout.strip())
    if not path.is_dir():
        raise Fehler(f"Tap {tap} nicht eingebunden; einbinden mit: bin/p94-brew-bootstrap")
    source_repo = _project_dir(tap, path, runner)
    head = runner.run(
        ["git", "-C", str(path), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]
    )
    if head.returncode == 0 and head.stdout.strip():
        branch = head.stdout.strip().removeprefix("origin/")
    else:
        branch = _git(runner, path, "rev-parse", "--abbrev-ref", "HEAD")
    return TapInfo(tap, path, source_repo, branch)


def check_source_repo(info: TapInfo, runner: Runner) -> None:
    """The project repository must be on the tap's branch and have a clean ``Formula/``."""
    branch = _git(runner, info.source_repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != info.branch:
        raise Fehler(
            f"Projekt {info.source_repo} steht auf Zweig {branch}, der Tap folgt {info.branch}; "
            f"wechseln mit: git -C {info.source_repo} switch {info.branch}"
        )
    dirty = _git(runner, info.source_repo, "status", "--porcelain", "--", "Formula")
    if dirty:
        raise Fehler(
            f"Formula/ im Projekt {info.source_repo} hat uncommittete Änderungen; "
            f"erst committen oder verwerfen (git -C {info.source_repo} status)"
        )


def verify(info: TapInfo, formula: str, text: str, runner: Runner, output: Output) -> bool:
    """Write the candidate into the tap clone, run style and audit, always restore the clone."""
    target = info.path / "Formula" / f"{formula}.rb"
    existed = target.exists()
    ok = True
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        name = f"{info.name}/{formula}"
        for command in (["style", "--formula", name], ["audit", "--formula", name]):
            result = runner.run(["brew", *command])
            if result.returncode != 0:
                ok = False
                output.error(f"brew {' '.join(command)} meldet Befunde für {formula}:")
                for line in (result.stdout + result.stderr).strip().splitlines():
                    output.info(f"  {line}")
                break
    finally:
        if existed:
            runner.run(["git", "-C", str(info.path), "checkout", "--", f"Formula/{formula}.rb"])
        else:
            target.unlink(missing_ok=True)
    return ok


def commit(info: TapInfo, formula: str, text: str, version: str, runner: Runner) -> None:
    """Write the formula into the project repository and commit it there."""
    target = info.source_repo / "Formula" / f"{formula}.rb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    rel = f"Formula/{formula}.rb"
    runner.run(["git", "-C", str(info.source_repo), "add", "--", rel], check=True)
    runner.run(
        [
            "git",
            "-C",
            str(info.source_repo),
            "commit",
            "-q",
            "-m",
            f"{formula} {version}",
            "--",
            rel,
        ],
        check=True,
    )


def fast_forward(info: TapInfo, runner: Runner) -> None:
    if info.source_repo.resolve() != info.path.resolve():
        runner.run(["git", "-C", str(info.path), "pull", "-q", "--ff-only"], check=True)


@dataclass
class Row:
    source: str
    formula: str = "-"
    old: str = "-"
    new: str = "-"
    result: str = ""
    changed: bool = False
    skipped: bool = False
    error: bool = False
    text: str = ""
    installed_hint: bool = field(default=False, repr=False)


def _version_of(tag: str | None) -> str:
    return tag[1:] if tag and tag.startswith("v") else "-"


def process_source(
    source: Source,
    info: TapInfo,
    runner: Runner,
    output: Output,
    dry_run: bool,
    cache_root: Path,
) -> list[Row]:
    """Check one source: fetch the newest tag, build candidates, verify and commit changes."""
    try:
        tag = gitsrc.newest(gitsrc.list_tags(source.url, runner))
    except gitsrc.RepoNotFound:
        return [Row(source.name, result="übersprungen: Repository nicht gefunden", skipped=True)]
    except Fehler as exc:
        return [Row(source.name, result=f"Fehler: {exc}", error=True)]
    if tag is None:
        return [Row(source.name, result="übersprungen: kein Tag vJJJJMMTT.NN", skipped=True)]
    new_version = _version_of(tag.name)
    try:
        cache = cache_root / f"{source.name}.git"
        gitsrc.fetch_tag(source.url, tag.name, cache, runner)
        available = gitsrc.list_templates(cache, tag.name, runner)
    except Fehler as exc:
        return [Row(source.name, result=f"Fehler: {exc}", error=True)]
    wanted = source.formulae if source.formulae is not None else available
    if not wanted:
        return [
            Row(
                source.name,
                new=new_version,
                result=f"übersprungen: keine Vorlage in {tag.name}",
                skipped=True,
            )
        ]
    rows: list[Row] = []
    for formula in wanted:
        row = Row(source.name, formula=formula, new=new_version)
        rows.append(row)
        if formula not in available:
            row.result = f"übersprungen: keine Vorlage in {tag.name}"
            row.skipped = True
            continue
        existing = info.path / "Formula" / f"{formula}.rb"
        old_text = existing.read_text(encoding="utf-8") if existing.exists() else None
        if old_text is not None:
            row.old = _version_of(formula_edit.get_source(old_text)[1])
        try:
            template = gitsrc.read_template(cache, tag.name, formula, runner)
            text = formula_edit.set_source(template, source.url, tag.name, tag.commit)
        except Fehler as exc:
            row.result = f"Fehler: {exc}"
            row.error = True
            continue
        if text == old_text:
            row.result = "aktuell"
            continue
        row.text = text
        row.changed = True
        if dry_run:
            row.result = "würde aktualisieren" if old_text is not None else "würde hinzufügen"
            continue
        if not verify(info, formula, text, runner, output):
            row.result = "Fehler: style oder audit meldet Befunde"
            row.error = True
            row.changed = False
            continue
        try:
            commit(info, formula, text, new_version, runner)
        except Fehler as exc:
            row.result = f"Fehler: {exc}"
            row.error = True
            row.changed = False
            continue
        row.result = "aktualisiert" if old_text is not None else "neu"
    return rows


def process_list(
    rel: str,
    info: TapInfo,
    runner: Runner,
    output: Output,
    dry_run: bool,
    system: steamos.SystemInfo,
) -> Row:
    """Generate the mirror formula of one package list; verify and commit it when it changed."""
    row = Row(rel)
    try:
        lst = steamos.load_list(info.path / rel)
        lst.path = rel
        row.formula = lst.formula
        sync_dbs, repo_order, local, mirror, build_id = system.load()
        resolved = steamos.resolve_list(lst, sync_dbs, repo_order, local, mirror)
        existing = info.path / "Formula" / f"{lst.formula}.rb"
        old_text = existing.read_text(encoding="utf-8") if existing.exists() else None
        row.old = steamos.version_label(old_text)
        text = steamos.generate(lst, resolved, build_id, old_text)
        if text is None:
            row.new = row.old
            row.result = "aktuell"
            return row
        row.new = steamos.version_label(text)
        row.text = text
        row.changed = True
        if dry_run:
            row.result = "würde aktualisieren" if old_text is not None else "würde hinzufügen"
        elif not verify(info, lst.formula, text, runner, output):
            row.result = "Fehler: style oder audit meldet Befunde"
            row.error = True
            row.changed = False
        else:
            commit(info, lst.formula, text, row.new, runner)
            row.result = "aktualisiert" if old_text is not None else "neu"
    except (Fehler, OSError, ValueError) as exc:
        row.result = f"Fehler: {exc}"
        row.error = True
        row.changed = False
    return row


def _acquire_lock():
    path = env.runtime_dir() / "p94-sync.lock"
    handle = open(path, "w")  # noqa: SIM115 - held until the process ends
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise Fehler(f"läuft schon (Sperre {path})") from None
    return handle


def _build_parser():
    parser = cli.make_parser(
        PROG,
        "Erzeugt die SteamOS-Spiegelformeln aus den Listen in steamos/, prüft und\n"
        "committet sie im Projektordner des Taps und aktualisiert installierte Formeln.\n"
        "Quellprojekte aus p94-sync.toml holt der Befehl ebenfalls.",
        epilog=(
            "Beispiele:\n"
            "  brew p94-sync --dry-run\n"
            "  brew p94-sync\n"
            "  brew p94-sync --no-upgrade claude-tools\n\n"
            f"Umgebung: {PROJECT_ENV} nennt den Projektordner des Taps (Vorgabe:\n"
            f"  ~/{PROJECT_DEFAULT}). Veröffentlichen mit git push bleibt Handarbeit.\n\n"
            "Exit-Status: 0 Erfolg, 1 Fehler, 2 falscher Aufruf."
        ),
    )
    parser.usage = f"{PROG} [OPTIONEN] [QUELLE ...]"
    args = parser.add_argument_group("Argumente")
    args.add_argument(
        "sources", nargs="*", metavar="QUELLE", help="nur diese Quellen (Vorgabe: alle)"
    )
    opts = parser.add_argument_group("Aktionen")
    opts.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="zeigt neue Tags und Änderungen, schreibt nichts",
    )
    opts.add_argument(
        "--no-upgrade", action="store_true", help="committet, ruft aber kein brew upgrade"
    )
    opts.add_argument(
        "--steamos-only",
        action="store_true",
        help="nur die Spiegel-Formeln aus den Listen erzeugen",
    )
    opts.add_argument("--no-steamos", action="store_true", help="die Spiegel-Formeln auslassen")
    opts.add_argument(
        "--tap", default=DEFAULT_TAP, metavar="NAME", help=f"anderer Tap (Vorgabe: {DEFAULT_TAP})"
    )
    cli.add_common_options(parser, __version__)
    return parser


def main(
    argv: list[str] | None = None,
    runner: Runner | None = None,
    system: steamos.SystemInfo | None = None,
) -> int:
    env.restore_user_env()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.steamos_only and args.no_steamos:
        parser.error("--steamos-only und --no-steamos schließen sich aus")
    output = Output(PROG, color=args.color, quiet=args.quiet, verbose=args.verbose)
    runner = runner or Runner(output=output)
    lock = _acquire_lock()
    try:
        return _run(args, output, runner, system or steamos.SystemInfo())
    finally:
        lock.close()


def _run(args, output: Output, runner: Runner, system: steamos.SystemInfo) -> int:
    info = tap_info(args.tap, runner)
    sources, steamos_lists = load_config(info.path / "p94-sync.toml")
    if args.steamos_only:
        sources = []
    elif args.sources:
        names = {s.name for s in sources}
        for unknown in sorted(set(args.sources) - names):
            output.warn(f"Quelle {unknown} steht nicht in p94-sync.toml")
        sources = [s for s in sources if s.name in args.sources]
    if not args.dry_run:
        check_source_repo(info, runner)
    cache_root = env.xdg_cache_home() / "p94-sync"
    rows: list[Row] = []
    for source in sources:
        output.detail(f"Quelle {source.name}: {source.url}")
        rows.extend(process_source(source, info, runner, output, args.dry_run, cache_root))
    if steamos_lists and not args.sources and not args.no_steamos:
        for rel in steamos_lists:
            rows.append(process_list(rel, info, runner, output, args.dry_run, system))

    output.table(
        ["QUELLE", "FORMEL", "ALT", "NEU", "ERGEBNIS"],
        [[r.source, r.formula, r.old, r.new, r.result] for r in rows],
    )

    changed = [r for r in rows if r.changed and not r.error]
    if changed and not args.dry_run:
        fast_forward(info, runner)
        if not args.no_upgrade:
            _upgrade(info, changed, runner, output)

    names = {r.source for r in rows}
    updated = {r.source for r in rows if r.changed and not r.error}
    skipped = {n for n in names if all(r.skipped for r in rows if r.source == n)}
    errors = sum(1 for r in rows if r.error)
    text = (
        f"{plural(len(names), 'Quelle', 'Quellen')} geprüft: "
        f"{len(updated)} aktualisiert, {len(skipped)} übersprungen"
    )
    if errors:
        output.warn(f"{text}, {plural(errors, 'Fehler', 'Fehler')}.")
        return cli.EXIT_ERROR
    output.note(f"{text}.")
    return cli.EXIT_OK


def _upgrade(info: TapInfo, changed: list[Row], runner: Runner, output: Output) -> None:
    upgraded = False
    for row in changed:
        name = f"{info.name}/{row.formula}"
        listed = runner.run(["brew", "list", "--formula", "--versions", name])
        if listed.returncode == 0 and listed.stdout.strip():
            output.info(f"Aktualisiere {name} ...")
            runner.run(["brew", "upgrade", name], check=True, capture=False)
            upgraded = True
        else:
            output.info(f"{row.formula}: nicht installiert; installieren: brew install {name}")
    if upgraded:
        output.info("Nächster Schritt: brew p94-link")


def main_entry() -> NoReturn:
    cli.run_main(PROG, main)

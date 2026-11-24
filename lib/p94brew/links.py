"""``brew p94-link``: link files from formulae into the home directory.

A formula ships ``share/p94-links/<formula>.links``; this module reads these lists, plans the
changes against the state file and applies them. Formulae never write into the home directory
themselves (grundlagen.md); everything the tool creates is recorded in the state file, so it never
touches a file it did not create.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from . import __version__, cli, env
from .cli import Fehler, Output, plural
from .runner import Runner

PROG = "brew p94-link"

# type -> (base, subfolder, target required); base is "home", "config" (XDG_CONFIG_HOME) or
# "data" (XDG_DATA_HOME).
TYPES: dict[str, tuple[str, str, bool]] = {
    "unit": ("config", "systemd/user", False),
    "skill": ("home", ".claude/skills", False),
    "autostart": ("config", "autostart", False),
    "fontconfig": ("config", "fontconfig/conf.d", False),
    "fish-conf": ("config", "fish/conf.d", False),
    "applications": ("data", "applications", False),
    "config": ("config", "", True),
    "data": ("data", "", True),
}
OPTIONS: dict[str, set[str]] = {"unit": {"enable"}}
ALL_OPTIONS = {opt for opts in OPTIONS.values() for opt in opts}
STATE_VERSION = 1


class LinkListError(Fehler):
    """Problem in a link list; the message starts with ``file:line``."""


@dataclass(frozen=True)
class Entry:
    formula: str
    type: str
    source: str
    target_rel: str
    options: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class Link:
    formula: str
    type: str
    source: Path  # path below prefix/opt/<formula>, not resolved
    target: Path
    options: tuple[str, ...]
    sha256: str | None

    def to_state(self) -> dict:
        return {
            "formula": self.formula,
            "type": self.type,
            "source": str(self.source),
            "target": str(self.target),
            "options": list(self.options),
            "sha256": self.sha256,
        }


@dataclass
class Plan:
    create: list[Link] = field(default_factory=list)
    replace: list[Link] = field(default_factory=list)
    remove: list[dict] = field(default_factory=list)
    conflicts: list[Link] = field(default_factory=list)
    daemon_reload: bool = False
    enable: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)  # all linked units, enabled or not
    disable: list[str] = field(default_factory=list)
    new_state: list[dict] = field(default_factory=list)
    current: int = 0  # links that are already correct


# --- parsing --------------------------------------------------------------------------------


def _check_relative(value: str, what: str, where: str, allow_dotdot: bool = False) -> None:
    parts = value.split("/")
    if value.startswith("/"):
        raise LinkListError(f"{where}: {what} '{value}' darf nicht absolut sein")
    if not allow_dotdot and ".." in parts:
        raise LinkListError(f"{where}: {what} '{value}' darf kein '..' enthalten")


def parse_link_list(path: Path, formula: str) -> list[Entry]:
    """Parse one ``.links`` file (format 1); raise ``LinkListError`` on the first problem."""
    entries: list[Entry] = []
    seen_format = False
    text = path.read_text(encoding="utf-8")
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        where = f"{path}:{number}"
        if not seen_format:
            if line.split() != ["format", "1"]:
                raise LinkListError(f"{where}: erste Zeile muss 'format 1' sein")
            seen_format = True
            continue
        fields = line.split()
        kind = fields[0]
        if kind not in TYPES:
            raise LinkListError(
                f"{where}: unbekannter Typ '{kind}'; erlaubt: {', '.join(sorted(TYPES))}"
            )
        if len(fields) < 2:
            raise LinkListError(f"{where}: QUELLE fehlt")
        source = fields[1]
        _check_relative(source, "QUELLE", where)
        target = None
        options: list[str] = []
        for item in fields[2:]:
            if item in ALL_OPTIONS:
                if item not in OPTIONS.get(kind, set()):
                    raise LinkListError(
                        f"{where}: Option '{item}' ist für den Typ {kind} nicht erlaubt"
                    )
                options.append(item)
            elif target is None:
                target = item
            else:
                raise LinkListError(f"{where}: unbekannte Option oder zweites Ziel '{item}'")
        if target is None:
            if TYPES[kind][2]:
                raise LinkListError(f"{where}: ZIEL fehlt (beim Typ {kind} Pflicht)")
            target = source.rstrip("/").rsplit("/", 1)[-1]
        _check_relative(target, "ZIEL", where)
        if target.startswith("."):
            raise LinkListError(f"{where}: ZIEL '{target}' darf nicht mit '.' beginnen")
        entries.append(Entry(formula, kind, source, target, tuple(options), number))
    if not seen_format:
        raise LinkListError(f"{path}: erste Zeile muss 'format 1' sein (Datei ist leer)")
    return entries


# --- resolving ------------------------------------------------------------------------------


def type_root(kind: str, home: Path, config_home: Path, data_home: Path) -> Path:
    """Target folder of a type (links are never created outside it)."""
    base, sub, _ = TYPES[kind]
    root = {"home": home, "config": config_home, "data": data_home}[base]
    return root / sub if sub else root


def _under(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(
    entries: list[Entry], prefix: Path, home: Path, config_home: Path, data_home: Path
) -> list[Link]:
    """Turn entries into links: the source must exist inside the keg of the formula."""
    links: list[Link] = []
    for entry in entries:
        keg = prefix / "opt" / entry.formula
        where = f"{entry.formula}.links:{entry.line}"
        source = keg / entry.source
        if not source.exists():
            raise LinkListError(f"{where}: Quelle {entry.source} fehlt in {keg}")
        if not _under(os.path.realpath(source), os.path.realpath(keg)):
            raise LinkListError(
                f"{where}: Quelle {entry.source} liegt außerhalb des Kegs von {entry.formula}"
            )
        target = type_root(entry.type, home, config_home, data_home) / entry.target_rel
        sha = _sha256_of(source) if entry.type == "unit" else None
        links.append(Link(entry.formula, entry.type, source, target, entry.options, sha))
    return links


# --- state ----------------------------------------------------------------------------------


def load_state(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Fehler(f"Zustandsdatei {path} unlesbar: {exc}; Datei prüfen oder löschen") from exc
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise Fehler(f"Zustandsdatei {path} hat eine unbekannte Version; Datei prüfen")
    return list(data.get("links", []))


def save_state(path: Path, links: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps({"version": STATE_VERSION, "links": links}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


# --- planning -------------------------------------------------------------------------------


def _readlink(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _unit_name(target: str | Path) -> str:
    return Path(target).name


def make_plan(
    links: list[Link],
    state: list[dict],
    selected: set[str] | None,
    remove_mode: bool,
    *,
    prefix: Path | None = None,
    protected: frozenset[str] | set[str] = frozenset(),
) -> Plan:
    """Compare wanted links with the file system and the state.

    ``selected``: formula names given on the command line or ``None`` for all.
    ``protected``: formulae whose list is broken; their state entries stay untouched.
    """
    prefix = prefix or env.brew_prefix()
    plan = Plan()

    def chosen(formula: str) -> bool:
        return selected is None or formula in selected

    wanted = {str(link.target): link for link in links if chosen(link.formula)}
    old = {entry["target"]: entry for entry in state}

    if remove_mode:
        for entry in state:
            if chosen(entry["formula"]):
                plan.remove.append(entry)
        for target, link in wanted.items():
            if target not in old and _readlink(link.target) == str(link.source):
                plan.remove.append(link.to_state())
    else:
        for entry in state:
            if not chosen(entry["formula"]) or entry["formula"] in protected:
                continue
            if entry["target"] not in wanted:
                plan.remove.append(entry)

    removed = {entry["target"] for entry in plan.remove}
    new_state = [
        entry
        for entry in state
        if entry["target"] not in removed and (remove_mode or entry["target"] not in wanted)
    ]

    if not remove_mode:
        for target, link in wanted.items():
            current = _readlink(link.target)
            if current is None and not os.path.lexists(link.target):
                plan.create.append(link)
            elif current == str(link.source):
                plan.current += 1
                previous = old.get(target)
                if link.type == "unit" and (
                    previous is None or previous.get("sha256") != link.sha256
                ):
                    plan.daemon_reload = True
            elif current is not None and any(
                _under(current, str(prefix / sub / link.formula)) for sub in ("opt", "Cellar")
            ):
                plan.replace.append(link)
            else:
                plan.conflicts.append(link)
                continue
            new_state.append(link.to_state())
            if link.type == "unit":
                plan.units.append(_unit_name(link.target))
            if "enable" in link.options:
                plan.enable.append(_unit_name(link.target))

    for link in plan.create + plan.replace:
        if link.type == "unit":
            plan.daemon_reload = True
    for entry in plan.remove:
        if entry.get("type") == "unit":
            plan.daemon_reload = True
            plan.disable.append(_unit_name(entry["target"]))
    plan.new_state = new_state
    return plan


# --- applying -------------------------------------------------------------------------------


def _tilde(path: str | Path, home: Path) -> str:
    text = str(path)
    prefix = str(home).rstrip("/") + "/"
    return "~/" + text[len(prefix) :] if text.startswith(prefix) else text


def _prune_empty_dirs(target: Path, root: Path) -> None:
    """Remove empty parent folders of ``target`` up to, but excluding, ``root``."""
    parent = target.parent
    while parent != root and _under(str(parent), str(root)):
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _atomic_symlink(source: str | Path, target: Path) -> None:
    """Create or replace the symlink ``target`` -> ``source`` in one step."""
    tmp = target.with_name(f".{target.name}.p94-link")
    if os.path.lexists(tmp):
        tmp.unlink()
    os.symlink(source, tmp)
    os.replace(tmp, target)


# Dependency folders that ``systemctl enable`` fills from [Install].
_DEPENDENCY_SUFFIXES = (".wants", ".requires", ".upholds")


def _dependency_links(unit_dir: Path, name: str) -> list[Path]:
    """Symlinks named ``name`` in ``unit_dir/*.wants`` and its siblings."""
    if not unit_dir.is_dir():
        return []
    found = []
    for folder in sorted(unit_dir.iterdir()):
        wanted = folder.name.endswith(_DEPENDENCY_SUFFIXES)
        if wanted and folder.is_dir() and not folder.is_symlink():
            candidate = folder / name
            if candidate.is_symlink():
                found.append(candidate)
    return found


def _systemctl(runner: Runner, *args: str) -> None:
    runner.change(["systemctl", "--user", *args], check=True)


def _disable(runner: Runner, name: str) -> None:
    """``disable --now``; a unit that is not loaded (its file is gone with the formula) is fine."""
    args = ["systemctl", "--user", "disable", "--now", name]
    result = runner.change(args)
    if result.returncode == 0:
        return
    text = f"{result.stderr}\n{result.stdout}"
    if any(hint in text for hint in ("not loaded", "does not exist", "No such file")):
        return
    lines = result.stderr.strip().splitlines()
    last = lines[-1] if lines else "keine Fehlerausgabe"
    raise Fehler(f"{shlex.join(args)} endete mit {result.returncode}: {last}")


def apply_plan(
    plan: Plan,
    state: list[dict],
    runner: Runner,
    output: Output,
    dry_run: bool,
    *,
    state_path: Path | None = None,
    home: Path | None = None,
    config_home: Path | None = None,
    data_home: Path | None = None,
    prefix: Path | None = None,
) -> int:
    """Carry out the plan; returns the exit code (1 with conflicts)."""
    prefix = prefix or env.brew_prefix()
    home = home or env.home()
    config_home = config_home or env.xdg_config_home()
    data_home = data_home or env.xdg_data_home()
    verb_link = "würde verlinken" if dry_run else "verlinkt"
    verb_remove = "würde entfernen" if dry_run else "entfernt"
    sym = output.ok_sym
    width = 15 if dry_run else 10

    # 1. stop units that go away
    for name in plan.disable:
        _disable(runner, name)

    # 2. remove links
    removed = 0
    for entry in plan.remove:
        target = Path(entry["target"])
        root = type_root(entry["type"], home, config_home, data_home)
        current = _readlink(target)
        own = current is not None and (current == entry["source"] or _under(current, str(prefix)))
        if not _under(str(target), str(root)):
            output.warn(
                f"{target} liegt außerhalb von {root}; aus dem Zustand genommen, nichts gelöscht"
            )
            continue
        if current is None:
            if os.path.lexists(target):
                output.warn(
                    f"{_tilde(target, home)} ist keine Verknüpfung von p94-link; "
                    "aus dem Zustand genommen"
                )
            continue
        if not own:
            output.warn(
                f"{_tilde(target, home)} zeigt nicht mehr auf Homebrew; "
                "aus dem Zustand genommen, nichts gelöscht"
            )
            continue
        output.result(f"{sym} {verb_remove.ljust(width)} {_tilde(target, home)}")
        removed += 1
        if not dry_run:
            target.unlink()
            _prune_empty_dirs(target, root)

    # 3. create and replace links
    created = 0
    for link in plan.create + plan.replace:
        output.result(f"{sym} {verb_link.ljust(width)} {_tilde(link.target, home)} → {link.source}")
        created += 1
        if not dry_run:
            link.target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            _atomic_symlink(link.source, link.target)

    for link in plan.conflicts:
        output.result(
            f"{output.fail_sym} {'Konflikt'.ljust(width)} {_tilde(link.target, home)}: "
            "Datei gehört nicht zu p94-link; verschieben oder löschen, dann erneut"
        )

    # 4. state
    if not dry_run and state_path is not None and (plan.new_state != state):
        save_state(state_path, plan.new_state)

    # 5. systemd
    reloaded = False
    if plan.daemon_reload:
        _systemctl(runner, "daemon-reload")
        reloaded = not dry_run
    for name in plan.enable:
        result = runner.run(["systemctl", "--user", "is-enabled", name])
        if result.stdout.strip() != "enabled":
            _systemctl(runner, "enable", name)

    # 6. systemctl enable follows the unit link through opt/ to Cellar/<version>/, and brew
    #    cleanup deletes that folder after an upgrade. systemd only uses the link name, so point
    #    the link at the unit link instead; it then survives upgrades. is-enabled still says
    #    "enabled" for a dangling link, so this check runs on every call, and for every linked
    #    unit: a setup command of the tool may have enabled it without the enable option.
    unit_dir = type_root("unit", home, config_home, data_home)
    verb_fix = "würde umbiegen" if dry_run else "umgebogen"
    fixed = 0
    for name in plan.units:
        unit = unit_dir / name
        for dependency in _dependency_links(unit_dir, name):
            current = _readlink(dependency)
            if current is None or current == str(unit) or not _under(current, str(prefix)):
                continue
            output.result(
                f"{sym} {verb_fix.ljust(width)} {_tilde(dependency, home)} → {_tilde(unit, home)}"
            )
            fixed += 1
            if not dry_run:
                _atomic_symlink(unit, dependency)

    # summary (ERF-2)
    conflicts = len(plan.conflicts)
    if not fixed:
        fixed_text = ""
    elif dry_run:
        counted = plural(fixed, "Aktivierungslink würde", "Aktivierungslinks würden")
        fixed_text = f", {counted} umgebogen"
    else:
        fixed_text = f", {plural(fixed, 'Aktivierungslink', 'Aktivierungslinks')} umgebogen"
    if dry_run:
        output.info(
            f"Trockenlauf: {plural(created, 'Link würde', 'Links würden')} angelegt, "
            f"{removed} würden entfernt, {plural(conflicts, 'Konflikt', 'Konflikte')}{fixed_text}"
        )
    elif created or removed or conflicts or fixed:
        text = (
            f"{plural(created, 'Link', 'Links')} angelegt, {removed} entfernt, "
            f"{plural(conflicts, 'Konflikt', 'Konflikte')}{fixed_text}"
        )
        if reloaded:
            text += "; systemctl --user daemon-reload ausgeführt"
        (output.note if not conflicts else output.warn)(text)
    else:
        output.note(f"alle Links aktuell ({plan.current})")
    return cli.EXIT_ERROR if conflicts else cli.EXIT_OK


# --- command line ---------------------------------------------------------------------------


def _build_parser():
    parser = cli.make_parser(
        PROG,
        "Verlinkt Dateien aus Homebrew-Formeln ins Home und entfernt veraltete Links.",
        epilog=(
            "Beispiele:\n"
            "  brew p94-link\n"
            "  brew p94-link --dry-run p94-hello\n"
            "  brew p94-link --remove p94-hello\n"
            "  brew p94-link --list\n\n"
            "Exit-Status: 0 Erfolg, 1 Fehler oder Konflikt, 2 falscher Aufruf."
        ),
        details=(
            "Format der Linkliste: share/p94-links/FORMEL.links, Zeilen TYP QUELLE [ZIEL] "
            "[OPTION]. Typen: unit, skill, autostart, fontconfig, fish-conf, applications, "
            "config, data. Der Befehl überschreibt nie eine fremde Datei: bei einem Konflikt "
            "endet er mit Exit 1. Zustand: ~/.local/state/p94-link/state.json. Seite: "
            "docs/p94-link.md."
        ),
    )
    parser.usage = f"{PROG} [OPTIONEN] [FORMEL ...]"
    args = parser.add_argument_group("Argumente")
    args.add_argument(
        "formulas", nargs="*", metavar="FORMEL", help="nur diese Formeln (Vorgabe: alle)"
    )
    opts = parser.add_argument_group("Aktionen")
    opts.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="zeigt Links und systemctl-Aufrufe, ändert nichts",
    )
    opts.add_argument(
        "--remove",
        action="store_true",
        help="entfernt die Links der genannten Formeln (ohne Namen: alle)",
    )
    opts.add_argument("--list", action="store_true", help="zeigt die verwalteten Links")
    cli.add_common_options(parser, __version__)
    return parser


def _collect(prefix: Path, selected: set[str] | None, home, config_home, data_home, output):
    """Read and resolve all link lists; returns (links, protected formulae, failures)."""
    links: list[Link] = []
    protected: set[str] = set()
    failures = 0
    list_dir = prefix / "share" / "p94-links"
    for path in sorted(list_dir.glob("*.links")) if list_dir.is_dir() else []:
        formula = path.name[: -len(".links")]
        if selected is not None and formula not in selected:
            continue
        if not (prefix / "opt" / formula).exists():
            continue
        try:
            entries = parse_link_list(path, formula)
            links.extend(resolve(entries, prefix, home, config_home, data_home))
        except LinkListError as exc:
            output.error(str(exc))
            protected.add(formula)
            failures += 1
    return links, protected, failures


def main(argv: list[str] | None = None) -> int:
    env.restore_user_env()
    args = _build_parser().parse_args(argv)
    output = Output(PROG, color=args.color, quiet=args.quiet, verbose=args.verbose)
    prefix = env.brew_prefix()
    home, config_home, data_home = env.home(), env.xdg_config_home(), env.xdg_data_home()
    state_path = env.xdg_state_home() / "p94-link" / "state.json"
    state = load_state(state_path)
    selected = set(args.formulas) if args.formulas else None

    if args.list:
        rows = [
            [e["formula"], e["type"], _tilde(e["target"], home)]
            for e in state
            if selected is None or e["formula"] in selected
        ]
        if rows:
            output.table(["FORMEL", "TYP", "ZIEL"], rows)
        else:
            output.info("keine verwalteten Links")
        return cli.EXIT_OK

    if selected:
        known = {e["formula"] for e in state} | {
            p.name[: -len(".links")] for p in (prefix / "share" / "p94-links").glob("*.links")
        }
        for name in sorted(selected - known):
            output.warn(f"Formel {name} hat keine Linkliste und keine verwalteten Links")

    links, protected, failures = _collect(prefix, selected, home, config_home, data_home, output)
    if not links and not state and not failures:
        output.note(f"keine Linklisten gefunden ({prefix / 'share' / 'p94-links'})")
        return cli.EXIT_OK

    plan = make_plan(links, state, selected, args.remove, prefix=prefix, protected=protected)
    needs_systemd = plan.daemon_reload or plan.enable or plan.disable
    if needs_systemd and not args.dry_run and not os.environ.get("XDG_RUNTIME_DIR"):
        raise Fehler(
            "systemd-User-Manager nicht erreichbar (XDG_RUNTIME_DIR fehlt); "
            "in einer Sitzung ausführen"
        )
    runner = Runner(dry_run=args.dry_run, output=output)
    code = apply_plan(
        plan,
        state,
        runner,
        output,
        args.dry_run,
        state_path=state_path,
        home=home,
        config_home=config_home,
        data_home=data_home,
        prefix=prefix,
    )
    return cli.EXIT_ERROR if failures else code


def main_entry() -> NoReturn:
    cli.run_main(PROG, main)


if __name__ == "__main__":
    main_entry()
    sys.exit(0)

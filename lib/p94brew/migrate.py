"""``p94-brew-migrate``: move old tool installs from ``~/.local`` to Homebrew.

Order matters (the login never breaks): first the chezmoi templates learn the Homebrew paths, then
every tool is installed, checked and only then are its old files moved to a backup folder, never
deleted. ``--rollback`` puts them back. ``--dry-run`` shows the plan and changes nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from . import __version__, cli, env
from .cli import EXIT_ERROR, EXIT_OK, Fehler, Output, plural
from .runner import Runner

PROG = "p94-brew-migrate"
BREW_PREFIX_DEFAULT = "/home/linuxbrew/.linuxbrew"
TEMPLATE_COMMIT = "claude, git: Homebrew-Pfade für graft, claude-brain und gh (homebrew-p94)"
GRAFT_PACKAGE = "@nanonets/graft"


@dataclass(frozen=True)
class Tool:
    key: str
    formula: str  # brew formula (or cask token)
    commands: tuple[str, ...]
    steps: str  # short description for the dry run
    cask: bool = False
    optional: bool = False  # only with --with-claude-code


TOOLS: tuple[Tool, ...] = (
    Tool(
        "gh",
        "gh",
        ("gh",),
        "installieren, chezmoi apply, Anmeldung prüfen, verschieben",
    ),
    Tool(
        "node",
        "node@24",
        ("node", "npm", "npx", "corepack", "graft"),
        "installieren, graft nachinstallieren, chezmoi apply, verschieben",
    ),
    Tool("neovim", "neovim", ("nvim",), "installieren, verschieben"),
    Tool("diff-so-fancy", "diff-so-fancy", ("diff-so-fancy",), "installieren, verschieben"),
    Tool("chezmoi", "chezmoi", ("chezmoi",), "installieren, verschieben"),
    Tool(
        "steamos-tools",
        "weegee/p94/steamos-tools",
        ("ethtool", "turbostat", "vainfo"),
        "installieren, verschieben",
    ),
    Tool(
        "claude",
        "claude-code@latest",
        ("claude",),
        "Cask installieren, verschieben",
        cask=True,
        optional=True,
    ),
)

EXCLUDED: tuple[tuple[str, str], ...] = (
    ("claude-tools-Übergang, claude-*-Wrapper", "werden eigens umgestellt"),
    ("p94-hig-Klon", "Skill-Klon, p94-Ersatz"),
    ("LACT", "/opt/lact, Tuning"),
    ("lst-*", "lst-check, Tuning"),
    ("steam-chat-lite", "eigenes Skript"),
    ("hdmi-audio-*", "Tuning"),
    ("discord-gamemode", "eigenes Projekt"),
    ("flatpak-auto-update", "wird durch steamos-unattended-upgrades ersetzt"),
)


@dataclass(frozen=True)
class Replacement:
    """One edit of a chezmoi template: every ``old`` text becomes its ``new`` text, or none."""

    file: str  # relative to the chezmoi source directory
    pairs: tuple[tuple[str, str], ...]


GRAFT_OLD = '{{- $graft := and (lookPath "node") (lookPath "graft") -}}'
GRAFT_NEW = (
    '{{- $graft := or (and (lookPath "node") (lookPath "graft")) '
    '(and (stat "/home/linuxbrew/.linuxbrew/opt/node@24/bin/node") '
    '(stat "/home/linuxbrew/.linuxbrew/bin/graft")) -}}'
)
BRAIN_OLD = '{{- $brain := lookPath "claude-brain" -}}'
BRAIN_NEW = (
    '{{- $brain := or (lookPath "claude-brain") '
    '(stat "/home/linuxbrew/.linuxbrew/bin/claude-brain") -}}'
)
IGNORE_OLD = '{{- if not (and (lookPath "node") (lookPath "graft")) }}'
IGNORE_NEW = (
    '{{- if not (or (and (lookPath "node") (lookPath "graft")) '
    '(and (stat "/home/linuxbrew/.linuxbrew/opt/node@24/bin/node") '
    '(stat "/home/linuxbrew/.linuxbrew/bin/graft"))) }}'
)
GH_COMMENT_OLD = (
    "{{- /* gh: /usr/bin auf Arch-Systemen, ~/.local/bin auf SteamOS, "
    "wo /usr schreibgeschützt ist */ -}}"
)
GH_COMMENT_NEW = (
    "{{- /* gh: /usr/bin auf Arch-Systemen, Homebrew oder ~/.local/bin auf SteamOS */ -}}"
)
GH_BLOCK_OLD = (
    '{{- if stat (joinPath .chezmoi.homeDir ".local/bin/gh") -}}\n'
    '{{-   $gh = joinPath .chezmoi.homeDir ".local/bin/gh" -}}'
)
GH_BLOCK_NEW = (
    '{{- if stat "/home/linuxbrew/.linuxbrew/bin/gh" -}}\n'
    '{{-   $gh = "/home/linuxbrew/.linuxbrew/bin/gh" -}}\n'
    '{{- else if stat (joinPath .chezmoi.homeDir ".local/bin/gh") -}}\n'
    '{{-   $gh = joinPath .chezmoi.homeDir ".local/bin/gh" -}}'
)

REPLACEMENTS: tuple[Replacement, ...] = (
    Replacement("dot_claude/settings.json.tmpl", ((GRAFT_OLD, GRAFT_NEW),)),
    Replacement("dot_claude/settings.json.tmpl", ((BRAIN_OLD, BRAIN_NEW),)),
    Replacement(".chezmoiignore", ((IGNORE_OLD, IGNORE_NEW),)),
    Replacement(
        "dot_config/git/config.tmpl",
        ((GH_COMMENT_OLD, GH_COMMENT_NEW), (GH_BLOCK_OLD, GH_BLOCK_NEW)),
    ),
)


@dataclass
class Context:
    home: Path
    prefix: Path
    state_dir: Path
    chezmoi_src: Path
    runner: Runner
    output: Output
    dry_run: bool = False
    push: bool = False
    backup_dir: Path | None = None
    manifest: list[dict] = field(default_factory=list)

    @property
    def brew(self) -> str:
        return str(self.prefix / "bin/brew")

    @property
    def local_bin(self) -> Path:
        return self.home / ".local/bin"


# --- old parts -------------------------------------------------------------------------------


def find_old_parts(home: Path, command: str) -> list[Path]:
    """The files that belong to ``~/.local/bin/COMMAND``: the entry point and what it points to."""
    entry = home / ".local/bin" / command
    if not os.path.lexists(entry):
        return []
    parts = [entry]
    if entry.is_symlink():
        target = Path(os.path.realpath(entry))
        for base in (home / ".local/opt", home / ".local/lib/node_modules"):
            try:
                rel = target.relative_to(os.path.realpath(base))
            except ValueError:
                continue
            if base.name == "opt":
                parts.append(base / rel.parts[0])
            elif rel.parts[0].startswith("@") and len(rel.parts) > 1:
                parts.append(base / rel.parts[0] / rel.parts[1])
            else:
                parts.append(base / rel.parts[0])
    return parts


def tool_old_parts(home: Path, tool: Tool) -> list[Path]:
    seen: list[Path] = []
    for command in tool.commands:
        for part in find_old_parts(home, command):
            if part not in seen:
                seen.append(part)
    # a folder first would hide its link target from the move: links before folders is enough, but
    # never list a path below another listed path
    return [p for p in seen if not any(q != p and _is_below(p, q) for q in seen)]


def _is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


# --- plan -------------------------------------------------------------------------------------


@dataclass
class ToolPlan:
    tool: Tool
    old: str  # path and version, or "-"
    new: str  # formula and version
    installed: bool
    parts: list[Path]

    @property
    def done(self) -> bool:
        return not self.parts and self.installed


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def _tilde(path: Path, home: Path) -> str:
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def plan(ctx: Context, tools: Sequence[Tool]) -> list[ToolPlan]:
    plans = []
    for tool in tools:
        parts = tool_old_parts(ctx.home, tool)
        old = "-"
        if parts:
            entry = parts[0]
            version = ""
            result = ctx.runner.run([str(entry), "--version"])
            if result.returncode == 0:
                version = _first_line(result.stdout).split(",")[0]
            old = f"{_tilde(entry, ctx.home)} {version}".strip()
        args = [ctx.brew, "info", "--json=v2", *(["--cask"] if tool.cask else []), tool.formula]
        info = ctx.runner.run(args)
        version, installed = "", False
        try:
            data = json.loads(info.stdout)
            if tool.cask:
                item = data["casks"][0]
                version, installed = str(item.get("version", "")), bool(item.get("installed"))
            else:
                item = data["formulae"][0]
                version = str(item.get("versions", {}).get("stable", ""))
                installed = bool(item.get("installed"))
        except (ValueError, KeyError, IndexError):
            pass
        state = "installiert" if installed else "nicht installiert"
        plans.append(
            ToolPlan(tool, old, f"{tool.formula} {version} ({state})".strip(), installed, parts)
        )
    return plans


# --- chezmoi templates ------------------------------------------------------------------------


def _line_of(text: str, snippet: str) -> int:
    return text[: text.index(snippet)].count("\n") + 1


def pending_replacements(src: Path) -> list[tuple[Replacement, str]]:
    """Replacements that still have to be made, each with its ``file:line`` label."""
    pending = []
    for item in REPLACEMENTS:
        path = src / item.file
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise Fehler(f"{path} unlesbar: {exc.strerror}") from exc
        if all(new in text for _, new in item.pairs):
            continue
        for old, _ in item.pairs:
            if old not in text:
                raise Fehler(
                    f"{path}: erwartete Zeile fehlt und die neue Fassung auch: "
                    f"{old.splitlines()[0]}; die Vorlage hat sich geändert, "
                    "Ersetzungen in migrate.py anpassen"
                )
        pending.append((item, f"{item.file}:{_line_of(text, item.pairs[0][0])}"))
    return pending


def apply_templates(ctx: Context) -> bool:
    """Make the chezmoi templates Homebrew-aware and commit them; True when something changed."""
    pending = pending_replacements(ctx.chezmoi_src)
    if not pending:
        ctx.output.note("Vorlagen: schon angepasst")
        return False
    if ctx.dry_run:
        for _, label in pending:
            ctx.output.result(f"würde ändern: {label}")
        return True
    files: list[str] = []
    for item, _ in pending:
        path = ctx.chezmoi_src / item.file
        text = path.read_text(encoding="utf-8")
        for old, new in item.pairs:
            text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")
        if item.file not in files:
            files.append(item.file)
    top = Path(
        ctx.runner.run(
            ["git", "-C", str(ctx.chezmoi_src), "rev-parse", "--show-toplevel"], check=True
        ).stdout.strip()
    )
    rel = [str((ctx.chezmoi_src / f).relative_to(top)) for f in files]
    ctx.runner.run(["git", "-C", str(top), "add", "--", *rel], check=True)
    ctx.runner.run(
        ["git", "-C", str(top), "commit", "-q", "-m", TEMPLATE_COMMIT, "--", *rel], check=True
    )
    ctx.output.note(
        f"Vorlagen angepasst und committet ({plural(len(pending), 'Änderung', 'Änderungen')})"
    )
    if ctx.push:
        ctx.runner.run(["git", "-C", str(top), "push", "-q"], check=True)
        ctx.output.note("chezmoi-Commit gepusht")
    return True


# --- backup and rollback ----------------------------------------------------------------------


def backup_move(paths: Sequence[Path], backup_dir: Path, manifest: list[dict], home: Path) -> None:
    """Move paths below ``backup_dir`` (same relative path as under the home) and record them."""
    for path in paths:
        if not os.path.lexists(path):
            continue
        dest = backup_dir / path.relative_to(home)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(dest):
            raise Fehler(f"{dest} existiert schon; Sicherung nicht überschrieben")
        shutil.move(str(path), str(dest))
        manifest.append({"source": str(path), "backup": str(dest)})
    (backup_dir / "manifest.json").write_text(
        json.dumps({"version": 1, "entries": manifest}, indent=2) + "\n", encoding="utf-8"
    )


def rollback(backup_dir: Path, output: Output, dry_run: bool) -> int:
    manifest_path = backup_dir / "manifest.json"
    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError) as exc:
        raise Fehler(
            f"{manifest_path} unlesbar ({exc}); keine Sicherung zum Zurückspielen"
        ) from exc
    code = EXIT_OK
    restored = 0
    for entry in reversed(entries):
        source, backup = Path(entry["source"]), Path(entry["backup"])
        if os.path.lexists(source):
            output.warn(f"{source} ist belegt; übersprungen, Sicherung bleibt in {backup}")
            code = EXIT_ERROR
            continue
        if not os.path.lexists(backup):
            output.warn(f"{backup} fehlt; {source} nicht wiederhergestellt")
            code = EXIT_ERROR
            continue
        if dry_run:
            output.result(f"würde zurückspielen: {backup} → {source}")
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(source))
            output.result(f"zurückgespielt: {source}")
        restored += 1
    count = plural(restored, "Eintrag", "Einträge")
    output.note(f"{count} würden zurückgespielt" if dry_run else f"{count} zurückgespielt")
    return code


def newest_backup(state_dir: Path) -> Path:
    candidates = sorted((state_dir / "homebrew-umstieg").glob("backup-*"))
    if not candidates:
        raise Fehler(f"keine Sicherung unter {state_dir / 'homebrew-umstieg'}; Ordner angeben")
    return candidates[-1]


# --- migrating one tool ----------------------------------------------------------------------


def _install(ctx: Context, tool: Tool) -> None:
    args = [ctx.brew, "install", *(["--cask"] if tool.cask else []), tool.formula]
    ctx.runner.run(args, check=True, capture=False)


def _chezmoi_apply(ctx: Context, path: Path) -> bool:
    return ctx.runner.run(["chezmoi", "apply", str(path)]).returncode == 0


def _check_gh(ctx: Context) -> str | None:
    """``None`` when gh works as git credential helper, else the reason."""
    config = ctx.home / ".config/git/config"
    helper = str(ctx.prefix / "bin/gh")
    if not _chezmoi_apply(ctx, config):
        return "chezmoi apply ~/.config/git/config schlug fehl"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if helper not in text:
        return f"der Helper in ~/.config/git/config zeigt nicht auf {helper}"
    # "gh auth status" needs no repository: it checks that the stored token is accepted.
    probe = ctx.runner.run([helper, "auth", "status"], env_extra={"GIT_TERMINAL_PROMPT": "0"})
    if probe.returncode != 0:
        return "gh meldet keine gültige Anmeldung (anmelden mit: gh auth login)"
    return None


def _install_graft(ctx: Context) -> None:
    package = ctx.home / ".local/lib/node_modules/@nanonets/graft/package.json"
    try:
        version = json.loads(package.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError) as exc:
        raise Fehler(f"graft-Version nicht lesbar aus {package}: {exc}") from exc
    node_bin = ctx.prefix / "opt/node@24/bin"
    npm = str(node_bin / "npm")
    spec = f"{GRAFT_PACKAGE}@{version}"
    # npm starts with "#!/usr/bin/env node": Homebrew's node goes first, or the old node in
    # ~/.local/bin runs npm and node-gyp. --prefix wins over a "prefix=~/.local" line in ~/.npmrc.
    # Homebrew's make bottle defaults CXX to g++-11 (its build host); node-gyp builds through make.
    base = (ctx.runner.env if ctx.runner.env is not None else os.environ).get("PATH", "")
    npm_env = {
        "PATH": os.pathsep.join(p for p in (str(node_bin), str(ctx.prefix / "bin"), base) if p),
        "CC": os.environ.get("CC", "cc"),
        "CXX": os.environ.get("CXX", "c++"),
    }
    target = ["--prefix", str(ctx.prefix)]
    run = ctx.runner.run([npm, "install", "-g", spec, *target], capture=False, env_extra=npm_env)
    if run.returncode != 0:
        ctx.output.warn(
            "npm install mit Build-Skripten scheitert; neuer Versuch mit --ignore-scripts"
        )
        ctx.runner.run(
            [npm, "install", "-g", "--ignore-scripts", spec, *target],
            check=True,
            capture=False,
            env_extra=npm_env,
        )
        script = ctx.prefix / "lib/node_modules/@nanonets/graft/dist/bin/graft.js"
        ctx.runner.run(["chmod", "+x", str(script)], check=True)
    shown = ctx.runner.run([str(ctx.prefix / "bin/graft"), "--version"], check=True).stdout
    if version not in shown:
        raise Fehler(f"graft --version meldet '{_first_line(shown)}', erwartet {version}")


def _has_graft_hooks(settings: Path) -> bool:
    try:
        return "graft-hooks" in settings.read_text(encoding="utf-8")
    except OSError:
        return False


def _old_npmrc(ctx: Context) -> list[Path]:
    """~/.npmrc when its only setting sends global installs to ~/.local (the old node setup).

    Such a file moves into the backup like the old node. With other settings it stays, and a
    warning names the line, since npm -g would keep installing into ~/.local.
    """
    npmrc = ctx.home / ".npmrc"
    try:
        text = npmrc.read_text(encoding="utf-8")
    except OSError:
        return []
    settings = [
        line.replace(" ", "")
        for line in (raw.strip() for raw in text.splitlines())
        if line and not line.startswith((";", "#"))
    ]
    old = {f"prefix={ctx.home}/.local", f"prefix={ctx.home}/.local/", "prefix=~/.local"}
    if settings and all(s in old for s in settings):
        return [npmrc]
    if any(s in old for s in settings):
        ctx.output.warn(
            "~/.npmrc setzt prefix=~/.local; npm -g installiert dann weiter nach ~/.local. "
            "Entferne die Zeile prefix=… aus ~/.npmrc"
        )
    return []


def _verify_commands(ctx: Context, tool: Tool) -> list[str]:
    """Commands whose ``command -v`` in a login shell does not point to Homebrew."""
    wrong = []
    for command in tool.commands:
        result = ctx.runner.run(["bash", "-lic", f"command -v {command}"])
        found = _first_line(result.stdout.splitlines()[-1]) if result.stdout.strip() else ""
        if not found.startswith(str(ctx.prefix) + "/"):
            wrong.append(f"{command} ({found or 'nicht gefunden'})")
    return wrong


def migrate_tool(tool: Tool, ctx: Context) -> bool:
    """Install, check and move one tool. A failure before the move leaves the old tool in place."""
    out = ctx.output
    parts = tool_old_parts(ctx.home, tool)
    try:
        _install(ctx, tool)
        if tool.key == "gh":
            reason = _check_gh(ctx)
            if reason:
                out.error(f"gh: {reason}; gh von Homebrew wird wieder entfernt, das alte gh bleibt")
                ctx.runner.run([ctx.brew, "uninstall", "gh"])
                _chezmoi_apply(ctx, ctx.home / ".config/git/config")
                return False
        elif tool.key == "node":
            _install_graft(ctx)
            settings = ctx.home / ".claude/settings.json"
            # The graft hooks run node on a fixed path below ~/.claude, so moving node does not
            # change them. Applying a file that already has them would only overwrite local
            # changes, and chezmoi stops without a terminal when the file changed since it wrote it.
            if not _has_graft_hooks(settings):
                if not _chezmoi_apply(ctx, settings):
                    raise Fehler(
                        "chezmoi apply ~/.claude/settings.json schlug fehl; "
                        "Unterschied ansehen: chezmoi diff ~/.claude/settings.json"
                    )
                if not _has_graft_hooks(settings):
                    raise Fehler(
                        "~/.claude/settings.json enthält nach dem Anwenden kein graft-hooks"
                    )
        elif tool.key == "claude":
            shown = ctx.runner.run([str(ctx.prefix / "bin/claude"), "--version"])
            if shown.returncode != 0:
                raise Fehler("claude --version aus Homebrew schlug fehl")
    except Fehler as exc:
        out.error(f"{tool.key}: {exc}; das alte Werkzeug bleibt an seinem Platz")
        return False
    if tool.key == "node":
        parts += _old_npmrc(ctx)
    if ctx.backup_dir is not None and parts:
        backup_move(parts, ctx.backup_dir, ctx.manifest, ctx.home)
    wrong = _verify_commands(ctx, tool)
    if wrong:
        out.error(f"{tool.key}: nach dem Umstellen zeigt {', '.join(wrong)} nicht auf Homebrew")
        return False
    out.note(f"{tool.key}: auf Homebrew umgestellt")
    return True


# --- main --------------------------------------------------------------------------------------


def _build_parser():
    parser = cli.make_parser(
        PROG,
        "Stellt Werkzeuge aus ~/.local auf Homebrew um, mit Sicherung und Rückweg.",
        epilog=(
            "Beispiele:\n"
            "  p94-brew-migrate --dry-run\n"
            "  p94-brew-migrate gh neovim\n"
            "  p94-brew-migrate --rollback\n\n"
            "Das Umstellen verschiebt die alten Dateien nach\n"
            "~/.local/state/homebrew-umstieg/backup-JJJJMMTT-HHMMSS/ und löscht nichts.\n"
            "Exit-Status: 0 Erfolg, 1 Fehler, 2 falscher Aufruf."
        ),
        details=(
            "Umgestellt werden gh, node, neovim, diff-so-fancy, chezmoi, ethtool, turbostat und "
            "vainfo. Er setzt eine chezmoi-Quelle voraus, deren Vorlagen er anpasst, und fragt "
            "vor dem Umstellen einmal nach (-y überspringt die Frage). --rollback stellt die "
            "neueste Sicherung wieder her. Seite: docs/homebrew-einrichten.md."
        ),
    )
    parser.usage = f"{PROG} [OPTIONEN] [WERKZEUG ...]\n       {PROG} --rollback [ORDNER]"
    args = parser.add_argument_group("Argumente")
    args.add_argument(
        "names",
        nargs="*",
        metavar="WERKZEUG",
        help="nur diese Werkzeuge (Vorgabe: alle); mit --rollback der Sicherungsordner",
    )
    opts = parser.add_argument_group("Aktionen")
    opts.add_argument(
        "-n", "--dry-run", action="store_true", help="zeigt je Werkzeug alt, neu und Schritte"
    )
    opts.add_argument(
        "--with-claude-code",
        action="store_true",
        help="Claude Code auf den Cask claude-code@latest umstellen",
    )
    opts.add_argument("--push", action="store_true", help="chezmoi-Commit pushen")
    opts.add_argument(
        "--rollback", action="store_true", help="Sicherung zurückspielen (Vorgabe: neueste)"
    )
    opts.add_argument("-y", "--yes", action="store_true", help="ohne Rückfrage")
    opts.add_argument(
        "--chezmoi-source",
        metavar="ORDNER",
        help="chezmoi-Quelle (für Tests; sonst chezmoi source-path)",
    )
    cli.add_common_options(parser, __version__)
    return parser


def _confirm(question: str) -> bool:
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        raise Fehler("ohne Terminal nur mit -y; abgebrochen, nichts geändert")
    while True:
        answer = input(f"{question} [j/N] ").strip().lower()
        if answer in ("j", "ja", "y", "yes"):
            return True
        if answer in ("", "n", "nein", "no"):
            return False


def _chezmoi_source(runner: Runner, given: str | None) -> Path:
    if given:
        return Path(given).expanduser().resolve()
    result = runner.run(["chezmoi", "source-path"])
    if result.returncode != 0 or not result.stdout.strip():
        raise Fehler("chezmoi source-path liefert nichts; ist chezmoi eingerichtet?")
    return Path(result.stdout.strip())


def main(argv: Sequence[str] | None = None, runner: Runner | None = None) -> int:
    env.restore_user_env()
    args = _build_parser().parse_args(argv)
    output = Output(PROG, color=args.color, quiet=args.quiet, verbose=args.verbose)
    home, prefix = env.home(), env.brew_prefix()
    state_dir = env.xdg_state_home()
    runner = runner or Runner(output=output)

    if args.rollback:
        if len(args.names) > 1:
            raise Fehler("--rollback nimmt höchstens einen Ordner")
        folder = Path(args.names[0]).expanduser() if args.names else newest_backup(state_dir)
        return rollback(folder, output, args.dry_run)

    by_key = {t.key: t for t in TOOLS}
    unknown = [n for n in args.names if n not in by_key]
    if unknown:
        raise Fehler(f"unbekanntes Werkzeug {unknown[0]}; bekannt: {', '.join(by_key)}")
    tools = [by_key[n] for n in args.names] if args.names else [t for t in TOOLS if not t.optional]
    if args.with_claude_code and by_key["claude"] not in tools:
        tools.append(by_key["claude"])
    if not (prefix / "bin/brew").exists():
        raise Fehler(f"Homebrew fehlt unter {prefix}; erst bin/p94-brew-bootstrap ausführen")

    ctx = Context(
        home, prefix, state_dir, _chezmoi_source(runner, args.chezmoi_source), runner, output,
        dry_run=args.dry_run, push=args.push,
    )  # fmt: skip
    if args.dry_run:
        return _dry_run(ctx, tools)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ctx.backup_dir = state_dir / "homebrew-umstieg" / f"backup-{stamp}"
    n = 1
    while ctx.backup_dir.exists():  # a second run within the same second must not reuse the folder
        n += 1
        ctx.backup_dir = state_dir / "homebrew-umstieg" / f"backup-{stamp}-{n}"
    if not args.yes and not _confirm(
        f"Werkzeuge auf Homebrew umstellen? Sicherung nach {ctx.backup_dir}"
    ):
        output.info("Abgebrochen, nichts geändert.")
        return EXIT_OK
    pending_replacements(
        ctx.chezmoi_src
    )  # a changed template stops the run before anything is touched
    ctx.backup_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    try:
        apply_templates(ctx)
        for tool in tools:
            if plan(ctx, [tool])[0].done:
                output.note(f"{tool.key}: schon umgestellt")
                continue
            if not migrate_tool(tool, ctx):
                failed += 1
    finally:
        if not ctx.manifest:
            shutil.rmtree(ctx.backup_dir, ignore_errors=True)
    if ctx.manifest:
        output.note(f"Sicherung: {ctx.backup_dir}; zurückspielen mit: p94-brew-migrate --rollback")
    if failed:
        output.error(f"{plural(failed, 'Werkzeug', 'Werkzeuge')} nicht umgestellt (Meldungen oben)")
        return EXIT_ERROR
    return EXIT_OK


def _dry_run(ctx: Context, tools: Sequence[Tool]) -> int:
    plans = plan(ctx, tools)
    rows = []
    for item in plans:
        steps = "schon umgestellt" if item.done else item.tool.steps
        rows.append([item.tool.key, item.old, item.new, steps])
    ctx.output.table(["WERKZEUG", "ALT", "NEU", "SCHRITTE"], rows)
    ctx.output.result("Bleibt:")
    for name, reason in EXCLUDED:
        ctx.output.result(f"  {name}: {reason}")
    apply_templates(ctx)
    return EXIT_OK


def main_entry() -> NoReturn:
    cli.run_main(PROG, main)


if __name__ == "__main__":
    main_entry()
    sys.exit(0)

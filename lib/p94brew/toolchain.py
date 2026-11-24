"""``brew p94-toolchain``: make Homebrew's gcc and clang usable with the SteamOS headers.

Homebrew's own gcc post-install step calls ``/usr/bin/cc``, which SteamOS does not have. The gcc
formula is therefore installed with ``--skip-post-install`` and pinned; this module rebuilds that
step with the headers of the formula ``steamos-sysroot`` (specs file, crt links, clang
configuration) and checks the result after every SteamOS or gcc update.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from . import __version__, cli, env, pacmandb
from .cli import Fehler, Output, plural
from .runner import Runner

PROG = "brew p94-toolchain"
TRIPLE = "x86_64-pc-linux-gnu"
MARKER = "# Written by brew p94-toolchain setup (homebrew-p94). Do not edit."
CRT_DIR = Path("/usr/lib")
CLANG_CONFIGS = ("clang.cfg", "clang++.cfg")
COMPILER_LINKS = {"cc": "gcc", "gcc": "gcc", "c++": "g++", "g++": "g++", "cpp": "cpp"}

C_PROBE = (
    "#include <stdio.h>\n#include <linux/version.h>\n"
    'int main(void) { puts("hallo 1"); return 0; }\n'
)
CXX_PROBE = (
    "#include <iostream>\n#include <string>\n#include <vector>\n"
    'int main() { std::vector<std::string> v{"hallo", "c++"}; std::cout << v[0] << " " << v[1]'
    " << std::endl; return 0; }\n"
)


@dataclass(frozen=True)
class Gcc:
    major: int
    driver: Path  # PREFIX/opt/gcc/bin/gcc-N
    libgcc_dir: Path  # directory of libgcc.a below the Cellar (holds specs and the crt links)
    opt_libgcc_dir: Path  # the same directory below PREFIX/opt/gcc (stable across upgrades)


@dataclass(frozen=True)
class Check:
    ok: bool | None  # True, False or None (warning, not applicable)
    label: str
    detail: str = ""
    hint: str = ""


def sysroot_include(prefix: Path) -> Path:
    return prefix / "opt/steamos-sysroot/libexec/sysroot/usr/include"


def _opt_path(prefix: Path, path: Path) -> Path:
    """Replace ``PREFIX/Cellar/gcc/<version>`` by ``PREFIX/opt/gcc``."""
    try:
        parts = path.relative_to(prefix / "Cellar/gcc").parts
    except ValueError:
        return path
    return prefix / "opt/gcc" / Path(*parts[1:])


def find_gcc(prefix: Path, runner: Runner) -> Gcc | None:
    """The highest installed gcc major below ``PREFIX/opt/gcc``; ``None`` if there is none."""
    best: tuple[int, Path] | None = None
    for candidate in (prefix / "opt/gcc/bin").glob("gcc-[0-9]*"):
        match = re.fullmatch(r"gcc-(\d+)", candidate.name)
        if match and (best is None or int(match.group(1)) > best[0]):
            best = (int(match.group(1)), candidate)
    if best is None:
        return None
    major, driver = best
    result = runner.run([str(driver), "-print-libgcc-file-name"])
    if result.returncode == 0 and result.stdout.strip():
        libgcc_dir = Path(os.path.normpath(result.stdout.strip())).parent
    else:
        # a broken specs file makes gcc fail even here; use the Homebrew layout so that
        # `setup` can repair it
        keg = Path(os.path.realpath(driver)).parent.parent
        libgcc_dir = keg / f"lib/gcc/current/gcc/{TRIPLE}/{major}"
        if not libgcc_dir.is_dir():
            return None
    return Gcc(major, driver, libgcc_dir, _opt_path(prefix, libgcc_dir))


def specs_addition(prefix: Path) -> str:
    """The block Homebrew appends to the specs, with the SteamOS headers instead of /usr/include."""
    return (
        "*cpp_unique_options:\n"
        f"+ -isysroot {prefix}/nonexistent -idirafter {prefix}/include"
        f" -idirafter {sysroot_include(prefix)}\n"
        "\n*link_libgcc:\n"
        f"+ -L{prefix}/lib/gcc/current -L{prefix}/lib\n"
        "\n*link:\n"
        f"+ --dynamic-linker {prefix}/lib/ld.so -rpath {prefix}/lib/gcc/current\n"
        "\n*homebrew_rpath:\n"
        f"-rpath {prefix}/lib\n"
        "\n"
    )


def render_specs(dumpspecs: str, prefix: Path) -> str:
    # exactly one blank line before the block: gcc 16 rejects a longer gap as "specs file malformed"
    text = dumpspecs.rstrip("\n") + "\n\n"
    return text.replace(" %o ", " %o %(homebrew_rpath) ") + specs_addition(prefix)


def clang_cfg(prefix: Path, gcc: Gcc) -> str:
    return (
        f"{MARKER}\n"
        f"-idirafter {prefix}/include\n"
        f"-idirafter {sysroot_include(prefix)}\n"
        f"--gcc-install-dir={gcc.opt_libgcc_dir}\n"
        # libgcc_s and libstdc++ of Homebrew's gcc live here, not in the gcc install dir
        f"-L{prefix}/lib/gcc/current\n"
        f"-Wl,-rpath,{prefix}/lib/gcc/current\n"
    )


def _read_packages(prefix: Path) -> list[dict] | None:
    path = prefix / "opt/steamos-sysroot/share/steamos-sysroot/packages.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _crt_files(crt_dir: Path) -> list[Path]:
    return sorted(crt_dir.glob("*crt?.o"))


def _tail(text: str, lines: int = 5) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _probe(runner: Runner, compiler: Path, source: str, suffix: str, label: str) -> Check:
    with tempfile.TemporaryDirectory(prefix="p94-toolchain-") as tmp:
        src = Path(tmp) / f"probe{suffix}"
        exe = Path(tmp) / "probe"
        src.write_text(source, encoding="utf-8")
        built = runner.run([str(compiler), "-o", str(exe), str(src)])
        if built.returncode != 0:
            return Check(False, f"{label}: Übersetzen scheitert", _tail(built.stderr))
        ran = runner.run([str(exe)])
        if ran.returncode != 0:
            return Check(False, f"{label}: Programm scheitert", _tail(ran.stderr))
    return Check(True, label)


def run_checks(
    prefix: Path,
    runner: Runner,
    local_db: dict[str, pacmandb.PkgDesc],
    crt_dir: Path = CRT_DIR,
) -> list[Check]:
    brew = str(env.brew_bin())
    checks: list[Check] = []
    gcc = find_gcc(prefix, runner)
    if gcc is not None:
        checks.append(Check(True, f"gcc {gcc.major} installiert ({gcc.driver})"))
    else:
        checks.append(
            Check(False, "gcc ist nicht installiert", hint="brew install --skip-post-install gcc")
        )

    pinned = runner.run([brew, "list", "--pinned"]).stdout.split()
    if "gcc" in pinned:
        checks.append(Check(True, "gcc angeheftet"))
    else:
        checks.append(Check(False, "gcc ist nicht angeheftet", hint="brew pin gcc"))

    packages = _read_packages(prefix)
    listed = runner.run([brew, "list", "--versions", "steamos-sysroot"]).stdout.split()
    if packages is None or len(listed) < 2:
        checks.append(
            Check(
                False,
                "steamos-sysroot ist nicht installiert",
                hint="brew install weegee/p94/steamos-sysroot",
            )
        )
    else:
        checks.append(Check(True, f"steamos-sysroot {listed[-1]} installiert"))
        mismatches = []
        for pkg in packages:
            installed = local_db.get(pkg.get("name", ""))
            if installed is not None and installed.version != pkg.get("version"):
                mismatches.append(
                    Check(
                        False,
                        f"{pkg['name']}-Header {pkg.get('version')} passen nicht zu "
                        f"{pkg['name']} {installed.version} im System. Erneuern: brew p94-sync",
                    )
                )
        if mismatches:
            checks.extend(mismatches)
        else:
            shown = ", ".join(
                f"{p['name']} {p['version']}" for p in packages if p.get("name") in local_db
            )
            checks.append(Check(True, f"Header passen zum System ({shown})"))

    ld_so = prefix / "lib/ld.so"
    if ld_so.exists():
        checks.append(Check(True, f"{ld_so} gültig"))
    else:
        checks.append(
            Check(
                False,
                f"{ld_so} fehlt",
                hint="Homebrew legt ihn beim nächsten brew install an",
            )
        )
    if gcc is None:
        return checks

    specs = gcc.libgcc_dir / "specs"
    include = str(sysroot_include(prefix))
    if specs.is_file() and include in specs.read_text(encoding="utf-8", errors="replace"):
        checks.append(Check(True, "specs-Datei mit SteamOS-Headern"))
    else:
        checks.append(
            Check(False, "specs-Datei ohne SteamOS-Header", hint="brew p94-toolchain setup")
        )

    crts = _crt_files(crt_dir)
    broken = [
        c.name
        for c in crts
        if not (gcc.libgcc_dir / c.name).is_symlink() or not (gcc.libgcc_dir / c.name).exists()
    ]
    if crts and not broken:
        checks.append(Check(True, f"crt-Dateien verlinkt ({len(crts)})"))
    elif not crts:
        checks.append(Check(False, f"keine crt-Dateien in {crt_dir}", hint="SteamOS-Abbild prüfen"))
    else:
        checks.append(
            Check(
                False,
                f"crt-Dateien nicht verlinkt ({', '.join(broken)})",
                hint="brew p94-toolchain setup",
            )
        )

    wrong = []
    for name, tool in COMPILER_LINKS.items():
        link = prefix / "bin" / name
        want = prefix / "opt/gcc/bin" / f"{tool}-{gcc.major}"
        if not link.exists() or os.path.realpath(link) != os.path.realpath(want):
            wrong.append(name)
    if not wrong:
        checks.append(Check(True, f"cc, gcc, c++, g++, cpp zeigen auf gcc {gcc.major}"))
    else:
        checks.append(
            Check(
                False,
                f"{', '.join(wrong)} zeigen nicht auf gcc {gcc.major}",
                hint="brew reinstall weegee/p94/steamos-sysroot",
            )
        )

    clang = prefix / "opt/llvm/bin/clang"
    if clang.exists():
        expected = clang_cfg(prefix, gcc)
        bad = []
        for name in CLANG_CONFIGS:
            path = prefix / "etc/clang" / name
            try:
                current = path.read_text(encoding="utf-8")
            except OSError:
                bad.append(name)
                continue
            if current != expected:
                bad.append(name)
        if bad:
            checks.append(
                Check(
                    False,
                    f"clang-Konfiguration fehlt oder ist veraltet ({', '.join(bad)})",
                    hint="brew p94-toolchain setup",
                )
            )
        else:
            checks.append(Check(True, "clang-Konfiguration"))
    else:
        checks.append(Check(None, "clang-Konfiguration: clang nicht installiert"))

    checks.append(_probe(runner, prefix / "bin/cc", C_PROBE, ".c", "Probe: C mit cc"))
    checks.append(_probe(runner, prefix / "bin/c++", CXX_PROBE, ".cpp", "Probe: C++ mit c++"))
    if clang.exists():
        checks.append(_probe(runner, clang, C_PROBE, ".c", "Probe: C mit clang"))
    return checks


def report(checks: Sequence[Check], output: Output) -> int:
    """Print the check lines (stdout) and the summary (stderr); exit code 1 on any failure."""
    for check in checks:
        detail = check.detail
        if check.ok is False and check.hint:
            detail = (detail + "\n" if detail else "") + f"Abhilfe: {check.hint}"
        output.check(check.ok, check.label, detail)
    output.out.flush()  # keep the summary after the lines when both go to one terminal
    failed = sum(1 for c in checks if c.ok is False)
    if failed:
        print(
            f"{output.fail_sym} {plural(failed, 'Prüfung', 'Prüfungen')} fehlgeschlagen",
            file=output.err,
        )
        return cli.EXIT_ERROR
    output.note("Toolchain bereit")
    return cli.EXIT_OK


def _local_db() -> dict[str, pacmandb.PkgDesc]:
    try:
        return pacmandb.read_local_db()
    except OSError:
        return {}


def setup(
    prefix: Path,
    runner: Runner,
    output: Output,
    dry_run: bool,
    crt_dir: Path = CRT_DIR,
    local_db: dict[str, pacmandb.PkgDesc] | None = None,
) -> int:
    gcc = find_gcc(prefix, runner)
    if gcc is None:
        raise Fehler("gcc fehlt: brew install --skip-post-install gcc")
    if not (prefix / "opt/steamos-sysroot").exists():
        raise Fehler("steamos-sysroot fehlt: brew install weegee/p94/steamos-sysroot")

    clang = prefix / "opt/llvm/bin/clang"
    cfg_dir = prefix / "etc/clang"
    configs = {cfg_dir / name: clang_cfg(prefix, gcc) for name in CLANG_CONFIGS}
    if clang.exists():
        for path in configs:
            if path.is_file():
                first = path.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
                if first != MARKER:
                    raise Fehler(
                        f"{path} stammt nicht von brew p94-toolchain; "
                        "Datei prüfen und verschieben, dann erneut ausführen"
                    )

    crts = _crt_files(crt_dir)
    specs = gcc.libgcc_dir / "specs"
    if dry_run:
        count = plural(len(crts), "crt-Datei", "crt-Dateien")
        output.info(f"würde {count} verlinken nach {gcc.libgcc_dir}")
        output.info(f"würde schreiben: {specs}")
        if clang.exists():
            for path in configs:
                output.info(f"würde schreiben: {path}")
        return cli.EXIT_OK

    for crt in crts:
        target = gcc.libgcc_dir / crt.name
        if target.is_symlink() or target.exists():
            target.unlink()
        os.symlink(crt, target)
    output.note(f"{plural(len(crts), 'crt-Datei', 'crt-Dateien')} verlinkt nach {gcc.libgcc_dir}")

    for stale in (specs, gcc.libgcc_dir / "specs.orig"):
        if stale.exists() or stale.is_symlink():
            stale.unlink()
    dumped = runner.run([str(gcc.driver), "-dumpspecs"], check=True).stdout
    (gcc.libgcc_dir / "specs.orig").write_text(dumped, encoding="utf-8")
    specs.write_text(render_specs(dumped, prefix), encoding="utf-8")
    output.note(f"specs geschrieben: {specs}")

    if clang.exists():
        cfg_dir.mkdir(parents=True, exist_ok=True)
        for path, text in configs.items():
            path.write_text(text, encoding="utf-8")
            output.note(f"clang-Konfiguration geschrieben: {path}")
    else:
        output.info("clang nicht installiert; clang-Konfiguration übersprungen")

    db = local_db if local_db is not None else _local_db()
    return report(run_checks(prefix, runner, db, crt_dir), output)


def _installed_version(prefix: Path, runner: Runner) -> str:
    listed = runner.run([str(env.brew_bin()), "list", "--versions", "gcc"]).stdout.split()
    return listed[-1] if len(listed) >= 2 else ""


def gcc_upgrade(
    prefix: Path,
    runner: Runner,
    output: Output,
    dry_run: bool,
    crt_dir: Path = CRT_DIR,
    local_db: dict[str, pacmandb.PkgDesc] | None = None,
) -> int:
    brew = str(env.brew_bin())
    old = find_gcc(prefix, runner)
    if old is None:
        raise Fehler("gcc fehlt: brew install --skip-post-install gcc")
    outdated = runner.run([brew, "outdated", "--formula", "--json=v2"], check=True)
    try:
        names = {f.get("name") for f in json.loads(outdated.stdout).get("formulae", [])}
    except ValueError as exc:
        raise Fehler(f"brew outdated lieferte kein JSON: {exc}") from exc
    if "gcc" not in names:
        output.note(f"gcc ist aktuell ({_installed_version(prefix, runner)})")
        return cli.EXIT_OK

    if dry_run:
        output.info("Schritte für das gcc-Upgrade:")
    runner.change([brew, "unpin", "gcc"])
    try:
        runner.change([brew, "install", "--skip-post-install", "gcc"], check=True, capture=False)
        if dry_run:
            output.info("würde ausführen: brew p94-toolchain setup")
            output.info("würde bei neuer Hauptversion: brew reinstall weegee/p94/steamos-sysroot")
        else:
            setup(prefix, runner, output, False, crt_dir, local_db)
            new = find_gcc(prefix, runner)
            if new is not None and new.major != old.major:
                output.info(f"gcc {old.major} wird gcc {new.major}; steamos-sysroot wird erneuert")
                runner.run(
                    [brew, "reinstall", "weegee/p94/steamos-sysroot"], check=True, capture=False
                )
    finally:
        runner.change([brew, "pin", "gcc"])
    if dry_run:
        return cli.EXIT_OK
    db = local_db if local_db is not None else _local_db()
    return report(run_checks(prefix, runner, db, crt_dir), output)


def _build_parser():
    parser = cli.make_parser(
        PROG,
        "Macht Homebrews gcc und clang mit den SteamOS-Headern nutzbar und prüft sie.",
        epilog=(
            "Beispiele:\n"
            "  brew p94-toolchain\n"
            "  brew p94-toolchain setup\n"
            "  brew p94-toolchain gcc-upgrade --dry-run\n\n"
            "Exit-Status: 0 Erfolg, 1 Fehler oder fehlgeschlagene Prüfung, 2 falscher Aufruf."
        ),
        details=(
            "check prüft gcc, Anheftung, Sysroot, Header und eine Probe; Exit 1, wenn etwas "
            "fehlt. setup schreibt specs-Datei, crt-Links und clang-Konfiguration; gcc-upgrade "
            "löst die Anheftung, installiert mit --skip-post-install, richtet neu ein und heftet "
            "wieder an. clang++ ist nicht Teil der Prüfung. Seite: docs/p94-toolchain.md."
        ),
    )
    parser.usage = f"{PROG} [AKTION] [OPTIONEN]"
    args = parser.add_argument_group("Unterbefehle")
    args.add_argument(
        "command",
        nargs="?",
        default="check",
        choices=("check", "setup", "gcc-upgrade"),
        metavar="check|setup|gcc-upgrade",
        help=(
            "check prüft Toolchain und Header (Vorgabe); setup schreibt specs, crt-Links und "
            "clang-Konfiguration und prüft dann; gcc-upgrade aktualisiert gcc kontrolliert"
        ),
    )
    opts = parser.add_argument_group("Aktionen")
    opts.add_argument(
        "-n", "--dry-run", action="store_true", help="zeigt die Schritte, ändert nichts"
    )
    cli.add_common_options(parser, __version__)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    env.restore_user_env()
    args = _build_parser().parse_args(argv)
    output = Output(PROG, color=args.color, quiet=args.quiet, verbose=args.verbose)
    prefix = env.brew_prefix()
    runner = Runner(dry_run=args.dry_run, output=output)
    if args.command == "setup":
        return setup(prefix, runner, output, args.dry_run)
    if args.command == "gcc-upgrade":
        return gcc_upgrade(prefix, runner, output, args.dry_run)
    return report(run_checks(prefix, runner, _local_db()), output)


def main_entry() -> NoReturn:
    cli.run_main(PROG, main)


if __name__ == "__main__":
    main_entry()
    sys.exit(0)

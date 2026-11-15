"""Generate mirror formulae from package lists and the SteamOS package database.

SteamOS has a read-only root and no compiler headers. A list in ``steamos/*.toml`` names Arch
packages from the SteamOS mirror; the generated formula downloads them (Homebrew checks the
sha256 from the image's own package database) and unpacks them below the keg.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import pacmandb
from .cli import Fehler
from .pacmandb import PkgDesc

LIST_KEYS = {"formula", "desc", "gcc_links", "package"}
PACKAGE_KEYS = {"name", "repo", "headers", "bin", "root", "test"}
MAX_LINE = 118
EXCLUDES = ".PKGINFO .BUILDINFO .MTREE .INSTALL"
HEADER_CHECKS = {"glibc": "stdio.h", "linux-api-headers": "linux/version.h"}


@dataclass
class Package:
    name: str
    headers: bool = False
    bin: list[str] = field(default_factory=list)
    test: list[str] = field(default_factory=list)
    repo: str | None = None
    root: bool = False


@dataclass
class PackageList:
    formula: str
    desc: str
    gcc_links: bool
    packages: list[Package]
    path: str


def _list_error(path: Path, message: str) -> Fehler:
    return Fehler(f"{path.name}: {message}")


def load_list(path: Path) -> PackageList:
    """Read and check a package list (keys and values as in the lists under ``steamos/``).

    A package needs ``headers``, ``bin`` or ``root``; ``root = true`` unpacks the whole package
    below ``libexec/root`` and links no commands (for libraries such as Python modules).
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _list_error(path, f"unlesbar: {exc}") from exc
    for key in data:
        if key not in LIST_KEYS:
            raise _list_error(path, f"unbekannter Schlüssel '{key}'")
    formula = data.get("formula")
    if not isinstance(formula, str) or not re.fullmatch(r"[a-z0-9-]+", formula):
        raise _list_error(path, "Schlüssel 'formula' fehlt oder passt nicht zu [a-z0-9-]+")
    desc = data.get("desc")
    if not isinstance(desc, str) or not desc or len(desc) >= 80 or desc.endswith("."):
        raise _list_error(
            path, "Schlüssel 'desc' fehlt, ist 80 Zeichen oder länger oder endet mit einem Punkt"
        )
    gcc_links = data.get("gcc_links", False)
    if not isinstance(gcc_links, bool):
        raise _list_error(path, "Schlüssel 'gcc_links' muss true oder false sein")
    packages: list[Package] = []
    for item in data.get("package", []):
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise _list_error(path, "[[package]] ohne 'name'")
        for key in item:
            if key not in PACKAGE_KEYS:
                raise _list_error(path, f"unbekannter Schlüssel '{key}' in [[package]] {name}")
        headers = item.get("headers", False)
        root = item.get("root", False)
        bins = item.get("bin", [])
        test = item.get("test", [])
        if not isinstance(headers, bool):
            raise _list_error(path, f"'headers' in [[package]] {name} muss true oder false sein")
        if not isinstance(root, bool):
            raise _list_error(path, f"'root' in [[package]] {name} muss true oder false sein")
        for key, value in (("bin", bins), ("test", test)):
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise _list_error(
                    path, f"'{key}' in [[package]] {name} muss eine Liste von Texten sein"
                )
        if not headers and not bins and not root:
            raise _list_error(path, f"[[package]] {name} braucht 'headers', 'bin' oder 'root'")
        if test and test[0] not in bins:
            raise _list_error(
                path, f"'test' in [[package]] {name} muss mit einem Befehl aus 'bin' beginnen"
            )
        packages.append(Package(name, headers, list(bins), list(test), item.get("repo"), root=root))
    if not packages:
        raise _list_error(path, "keine [[package]]-Einträge")
    return PackageList(formula, desc, gcc_links, packages, path.as_posix())


@dataclass
class Resolved:
    package: Package
    desc: PkgDesc
    url: str
    lib_wrapper: bool = False


def resolve_list(
    lst: PackageList,
    sync_dbs: dict[str, dict[str, PkgDesc]],
    repo_order: list[str],
    local: dict[str, PkgDesc],
    mirror: str,
) -> list[Resolved]:
    """Find every package in the sync databases and check version and dependencies."""
    in_list = {p.name for p in lst.packages}
    available = set(local)
    for desc in local.values():
        available.update(pacmandb.dep_name(p) for p in desc.provides)
    resolved: list[Resolved] = []
    for package in lst.packages:
        repos = [package.repo] if package.repo else repo_order
        found = next(
            (sync_dbs[r][package.name] for r in repos if package.name in sync_dbs.get(r, {})), None
        )
        if found is None:
            raise Fehler(
                f"Paket {package.name} steht in keiner Paketdatenbank ({', '.join(repos)})"
            )
        installed = local.get(package.name)
        if installed is not None and installed.version != found.version:
            raise Fehler(
                f"{package.name}: Paketdatenbank hat {found.version}, das System {installed.version}; "
                "erst SteamOS-Update abschließen oder neu starten"
            )
        lib_wrapper = False
        for dep in found.depends:
            name = pacmandb.dep_name(dep)
            if name in available:
                continue
            if name in in_list:
                lib_wrapper = True
                continue
            raise Fehler(
                f"{package.name} braucht {name}, das weder im Abbild noch in der Liste steht; "
                f"{name} zur Liste hinzufügen"
            )
        url = pacmandb.package_url(mirror, found.repo, found.filename)
        resolved.append(Resolved(package, found, url, lib_wrapper))
    return resolved


def class_name(formula: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in formula.split("-"))


def _call(indent: str, name: str, args: list[str]) -> list[str]:
    """A Ruby call on one line, or one argument per line when it gets too long."""
    one = f"{indent}{name} " + ", ".join(args)
    if len(one) <= MAX_LINE:
        return [one]
    pad = indent + " " * (len(name) + 1)
    lines = [f"{indent}{name} {args[0]},"]
    lines += [f"{pad}{arg}," for arg in args[1:-1]]
    lines.append(f"{pad}{args[-1]}")
    return lines


def _extract(indent: str, item: Resolved) -> list[str]:
    """bsdtar calls for one package (the file sits in the current directory)."""
    file_arg = f'"./{item.desc.filename}"'
    lines: list[str] = []
    if item.package.headers:
        lines += _call(
            indent, "system", ['"bsdtar"', '"-xf"', file_arg, '"-C"', "sysroot", '"usr/include"']
        )
    if item.package.bin or item.package.root:
        lines += _call(
            indent, "system", ['"bsdtar"', '"-xf"', file_arg, '"-C"', "root", "*excludes"]
        )
    return lines


def render(lst: PackageList, resolved: list[Resolved], version: str, revision: int) -> str:
    """The Ruby text of the formula."""
    first = resolved[0]
    out: list[str] = [
        f"# Generated by brew p94-sync from {lst.path} and the SteamOS package database.",
        "# Do not edit: change the list and run `brew p94-sync`.",
    ]
    for item in resolved:
        licenses = ", ".join(item.desc.licenses) or "unknown"
        out.append(f"# License of {item.desc.name}: {licenses}")
    out += [
        f"class {class_name(lst.formula)} < Formula",
        f'  desc "{lst.desc}"',
        '  homepage "https://steamdeck-packages.steamos.cloud/archlinux-mirror/"',
        f'  url "{first.url}",',
        "      using: :nounzip",
        f'  version "{version}"',
        f'  sha256 "{first.desc.sha256}"',
        "  license :cannot_represent",
    ]
    if revision > 0:
        out.append(f"  revision {revision}")
    out += ["", "  depends_on :linux", ""]
    for item in resolved[1:]:
        out += [
            f'  resource "{item.desc.name}" do',
            f'    url "{item.url}",',
            "        using: :nounzip",
            f'    sha256 "{item.desc.sha256}"',
            "  end",
            "",
        ]
    has_headers = any(i.package.headers for i in resolved)
    has_bin = any(i.package.bin for i in resolved)
    has_root = any(i.package.bin or i.package.root for i in resolved)
    out.append("  def install")
    if has_headers:
        out += ['    sysroot = libexec/"sysroot"', "    sysroot.mkpath"]
    if has_root:
        out += [
            '    root = libexec/"root"',
            "    root.mkpath",
            f'    excludes = %w[{EXCLUDES}].flat_map {{ |f| ["--exclude", f] }}',
        ]
    for index, item in enumerate(resolved):
        extract = _extract("    " if index == 0 else "      ", item)
        if not extract:
            continue
        if index == 0:
            out += extract
        else:
            out.append(f'    resource("{item.desc.name}").stage do')
            out += extract
            out.append("    end")
    if has_bin:
        for wrapped in (False, True):
            cmds = [c for i in resolved if i.lib_wrapper == wrapped for c in i.package.bin]
            if not cmds:
                continue
            out += [
                "",
                f"    %w[{' '.join(cmds)}].each do |cmd|",
                '      src = [root/"usr/bin"/cmd, root/"usr/sbin"/cmd].find(&:exist?)',
                '      raise "#{cmd} fehlt im Paket" if src.nil?',
                "",
            ]
            if wrapped:
                out.append('      (bin/cmd).write_env_script src, LD_LIBRARY_PATH: root/"usr/lib"')
            else:
                out.append("      bin.install_symlink src => cmd")
            out.append("    end")
        out += [
            '    man.install (root/"usr/share/man").children if (root/"usr/share/man").directory?',
            '    bash_comp = root/"usr/share/bash-completion/completions"',
            '    (share/"bash-completion/completions").install bash_comp.children if bash_comp.directory?',
            '    fish_comp = root/"usr/share/fish/vendor_completions.d"',
            '    (share/"fish/vendor_completions.d").install fish_comp.children if fish_comp.directory?',
        ]
    if lst.gcc_links:
        out += [
            "",
            '    gcc_bin = HOMEBREW_PREFIX/"opt/gcc/bin"',
            '    majors = gcc_bin.glob("gcc-[0-9]*").filter_map { |p| p.basename.to_s[/\\Agcc-(\\d+)\\z/, 1]&.to_i }',
            "    major = majors.max",
            '    raise "gcc fehlt: brew install --skip-post-install gcc" if major.nil?',
            "",
            '    links = { "cc" => "gcc", "gcc" => "gcc", "c++" => "g++", "g++" => "g++", "cpp" => "cpp" }',
            "    links.each do |name, tool|",
            '      bin.install_symlink gcc_bin/"#{tool}-#{major}" => name',
            "    end",
        ]
    out += ["", '    (pkgshare/"packages.json").write <<~JSON', "      ["]
    for index, item in enumerate(resolved):
        comma = "," if index < len(resolved) - 1 else ""
        out += [
            "        {",
            f'          "name": "{item.desc.name}",',
            f'          "version": "{item.desc.version}",',
            f'          "repo": "{item.desc.repo}",',
            f'          "file": "{item.desc.filename}",',
            f'          "sha256": "{item.desc.sha256}"',
            f"        }}{comma}",
        ]
    out += ["      ]", "    JSON", "  end", "", "  test do"]
    for item in resolved:
        if item.package.headers:
            header = HEADER_CHECKS.get(item.package.name)
            target = f"include/{header}" if header else "include"
            out.append(f'    assert_path_exists libexec/"sysroot/usr/{target}"')
    if any(i.package.root and not i.package.bin for i in resolved):
        out.append('    assert_path_exists libexec/"root/usr"')
    for item in resolved:
        for cmd in item.package.bin:
            out.append(f'    assert_predicate bin/"{cmd}", :executable?')
        if item.package.test:
            args = ", ".join(f'"{a}"' for a in item.package.test[1:])
            call = f'    system bin/"{item.package.test[0]}"'
            out.append(call + (f", {args}" if args else ""))
    out += ["  end", "end", ""]
    return "\n".join(out)


_VERSION_LINE = re.compile(r"^[ \t]*(version|revision) ")


def strip_version_lines(text: str) -> str:
    """The text without its ``version`` and ``revision`` lines (used to detect changes)."""
    return "".join(line for line in text.splitlines(keepends=True) if not _VERSION_LINE.match(line))


def read_version(text: str) -> tuple[str | None, int]:
    version = re.search(r'^[ \t]*version "([^"]+)"', text, re.MULTILINE)
    revision = re.search(r"^[ \t]*revision (\d+)", text, re.MULTILINE)
    return (version.group(1) if version else None, int(revision.group(1)) if revision else 0)


def generate(
    lst: PackageList, resolved: list[Resolved], build_id: str, existing: str | None
) -> str | None:
    """New formula text, or ``None`` when nothing changed apart from version and revision."""
    fresh = render(lst, resolved, build_id, 0)
    if existing is None:
        return fresh
    if strip_version_lines(existing) == strip_version_lines(fresh):
        return None
    old_version, old_revision = read_version(existing)
    revision = old_revision + 1 if old_version == build_id else 0
    return render(lst, resolved, build_id, revision)


def version_label(text: str | None) -> str:
    """``20261023.100`` or ``20261023.100_1`` (with revision), ``-`` for no formula."""
    if text is None:
        return "-"
    version, revision = read_version(text)
    if version is None:
        return "-"
    return f"{version}_{revision}" if revision else version


@dataclass
class SystemInfo:
    """Where the image keeps its package data; replaceable in tests."""

    db_dir: Path = pacmandb.DB_DIR
    pacman_conf: Path = Path("/etc/pacman.conf")
    mirrorlist: Path = Path("/etc/pacman.d/mirrorlist")
    os_release: Path = Path("/etc/os-release")

    def load(self) -> tuple[dict[str, dict[str, PkgDesc]], list[str], dict[str, PkgDesc], str, str]:
        repos = pacmandb.repos_from_pacman_conf(self.pacman_conf)
        sync = {}
        for repo in repos:
            db = self.db_dir / "sync" / f"{repo}.db"
            if db.exists():
                sync[repo] = pacmandb.read_sync_db(db, repo)
        local = pacmandb.read_local_db(self.db_dir / "local")
        return (
            sync,
            repos,
            local,
            pacmandb.mirror_template(self.mirrorlist),
            pacmandb.os_build_id(self.os_release),
        )

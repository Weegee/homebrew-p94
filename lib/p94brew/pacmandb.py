"""Read the SteamOS package databases (pacman format) of the read-only image."""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass
from pathlib import Path

DB_DIR = Path("/usr/lib/holo/pacmandb")


@dataclass(frozen=True)
class PkgDesc:
    name: str
    version: str
    filename: str = ""
    sha256: str = ""
    depends: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    licenses: tuple[str, ...] = ()
    repo: str = ""


def parse_desc(text: str, repo: str) -> PkgDesc:
    """Parse a ``desc`` file: blocks ``%KEY%`` followed by value lines up to a blank line."""
    blocks: dict[str, list[str]] = {}
    key = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("%") and stripped.endswith("%") and len(stripped) > 2:
            key = stripped[1:-1]
            blocks[key] = []
        elif not stripped:
            key = None
        elif key is not None:
            blocks[key].append(stripped)

    def one(name: str) -> str:
        return blocks.get(name, [""])[0] if blocks.get(name) else ""

    return PkgDesc(
        name=one("NAME"),
        version=one("VERSION"),
        filename=one("FILENAME"),
        sha256=one("SHA256SUM"),
        depends=tuple(blocks.get("DEPENDS", [])),
        provides=tuple(blocks.get("PROVIDES", [])),
        licenses=tuple(blocks.get("LICENSE", [])),
        repo=repo,
    )


def read_sync_db(path: Path, repo: str) -> dict[str, PkgDesc]:
    """Read a sync database (a gzip or zstd tar of ``<name>-<version>/desc`` files)."""
    packages: dict[str, PkgDesc] = {}
    with tarfile.open(path, "r:*") as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith("/desc"):
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                desc = parse_desc(handle.read().decode("utf-8", errors="replace"), repo)
                if desc.name:
                    packages[desc.name] = desc
    return packages


def read_local_db(path: Path = DB_DIR / "local") -> dict[str, PkgDesc]:
    """Read the database of installed packages (one folder per package)."""
    packages: dict[str, PkgDesc] = {}
    for desc_file in sorted(path.glob("*/desc")):
        desc = parse_desc(desc_file.read_text(encoding="utf-8", errors="replace"), "local")
        if desc.name:
            packages[desc.name] = desc
    return packages


def repos_from_pacman_conf(path: Path = Path("/etc/pacman.conf")) -> list[str]:
    """Repository sections of pacman.conf in order, without ``[options]``."""
    repos = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if match and match.group(1) != "options":
            repos.append(match.group(1))
    return repos


def mirror_template(path: Path = Path("/etc/pacman.d/mirrorlist")) -> str:
    """The first ``Server =`` value of the mirror list."""
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*Server\s*=\s*(\S+)", line)
        if match:
            return match.group(1)
    raise ValueError(f"{path}: kein Server-Eintrag")


def package_url(template: str, repo: str, filename: str, arch: str = "x86_64") -> str:
    base = template.replace("$repo", repo).replace("$arch", arch)
    return f"{base.rstrip('/')}/{filename}"


def dep_name(dep: str) -> str:
    """``libcap.so=2-64`` -> ``libcap.so``; ``linux-api-headers>=4.10`` -> ``linux-api-headers``."""
    return re.split(r"[<>=]", dep, maxsplit=1)[0]


def os_build_id(path: Path = Path("/etc/os-release")) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("BUILD_ID="):
            return line.split("=", 1)[1].strip().strip('"')
    raise ValueError(f"{path}: BUILD_ID fehlt")

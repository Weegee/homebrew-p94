"""Small SteamOS package databases for tests (no real system paths)."""

from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path

from p94brew.steamos import SystemInfo


def desc_text(
    name: str,
    version: str,
    *,
    sha: str = "",
    depends: list[str] | None = None,
    provides: list[str] | None = None,
    licenses: list[str] | None = None,
) -> str:
    blocks = [("NAME", [name]), ("VERSION", [version])]
    if sha:
        blocks.insert(0, ("FILENAME", [f"{name}-{version}-x86_64.pkg.tar.zst"]))
        blocks.append(("SHA256SUM", [sha]))
    for key, values in (("LICENSE", licenses), ("DEPENDS", depends), ("PROVIDES", provides)):
        if values:
            blocks.append((key, values))
    return "".join(f"%{key}%\n" + "\n".join(values) + "\n\n" for key, values in blocks)


def _desc_name(text: str) -> str:
    lines = text.splitlines()
    name = lines[lines.index("%NAME%") + 1]
    version = lines[lines.index("%VERSION%") + 1]
    return f"{name}-{version}"


def make_system(
    root: Path, sync: dict[str, list[str]], local: list[str], build_id: str = "20261023.100"
) -> SystemInfo:
    db_dir = root / "pacmandb"
    if db_dir.exists():  # tests may build several systems in one folder
        shutil.rmtree(db_dir)
    (db_dir / "sync").mkdir(parents=True)
    (db_dir / "local").mkdir()
    for repo, descs in sync.items():
        with tarfile.open(db_dir / "sync" / f"{repo}.db", "w:gz") as tar:
            for text in descs:
                data = text.encode()
                info = tarfile.TarInfo(f"{_desc_name(text)}/desc")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    for text in local:
        folder = db_dir / "local" / _desc_name(text)
        folder.mkdir()
        (folder / "desc").write_text(text)
    conf = root / "pacman.conf"
    conf.write_text(
        "[options]\nDBPath = /x\n\n"
        + "".join(f"[{r}]\nInclude = /etc/pacman.d/mirrorlist\n\n" for r in sync)
    )
    mirrorlist = root / "mirrorlist"
    mirrorlist.write_text(
        "# comment\nServer = https://mirror.example/archlinux-mirror/$repo/os/$arch\n"
    )
    os_release = root / "os-release"
    os_release.write_text(f"ID=steamos\nBUILD_ID={build_id}\n")
    return SystemInfo(db_dir, conf, mirrorlist, os_release)

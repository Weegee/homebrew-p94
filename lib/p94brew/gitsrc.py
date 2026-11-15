"""Read tags and formula templates from the git repositories of the source projects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .cli import Fehler
from .runner import Runner

TAG_RE = re.compile(r"^v(\d{8})\.(\d{2})$")
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}
_CREDENTIALS = re.compile(r"(://)[^/@\s]+@")


@dataclass(frozen=True)
class Tag:
    name: str
    commit: str


class RepoNotFound(Fehler):
    """The repository does not exist (or the account cannot see it)."""


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return _CREDENTIALS.sub(r"\1", lines[-1]) if lines else "keine Fehlerausgabe"


def list_tags(url: str, runner: Runner) -> list[Tag]:
    """Tags ``vJJJJMMTT.NN`` of a remote; for annotated tags the commit behind the tag."""
    result = runner.run(["git", "ls-remote", "--tags", url], env_extra=_GIT_ENV)
    if result.returncode != 0:
        err = result.stderr
        if "Repository not found" in err or "does not appear to be a git repository" in err:
            clean_url = _CREDENTIALS.sub(r"\1", url)
            raise RepoNotFound(f"Repository nicht gefunden: {clean_url}")
        raise Fehler(f"git ls-remote endete mit {result.returncode}: {_last_line(err)}")
    commits: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/") :]
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            commits[name] = sha
    commits.update(peeled)
    return [Tag(name, sha) for name, sha in commits.items() if TAG_RE.match(name)]


def newest(tags: list[Tag]) -> Tag | None:
    """The tag with the highest (date, NN)."""
    if not tags:
        return None
    return max(tags, key=lambda t: tuple(int(g) for g in TAG_RE.match(t.name).groups()))


def fetch_tag(url: str, tag: str, cache: Path, runner: Runner) -> None:
    """Fetch one tag (depth 1) into a bare cache repository."""
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        runner.run(["git", "init", "--bare", "-q", str(cache)], check=True)
    runner.run(
        [
            "git",
            "-C",
            str(cache),
            "fetch",
            "-q",
            "--depth=1",
            "--no-tags",
            "--force",
            url,
            f"refs/tags/{tag}:refs/tags/{tag}",
        ],
        check=True,
        env_extra=_GIT_ENV,
    )


def list_templates(cache: Path, tag: str, runner: Runner) -> list[str]:
    """Formula names of ``packaging/homebrew/*.rb`` in a tag."""
    result = runner.run(
        ["git", "-C", str(cache), "ls-tree", "--name-only", tag, "packaging/homebrew/"]
    )
    if result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        path = Path(line.strip())
        if path.suffix == ".rb":
            names.append(path.stem)
    return sorted(names)


def read_template(cache: Path, tag: str, formula: str, runner: Runner) -> str:
    result = runner.run(
        ["git", "-C", str(cache), "show", f"{tag}:packaging/homebrew/{formula}.rb"], check=True
    )
    return result.stdout

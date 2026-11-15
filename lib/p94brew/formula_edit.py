"""Edit the source statement (``url``, ``tag:``, ``revision:``) of a formula text."""

from __future__ import annotations

import re

from .cli import Fehler

SOURCE_TAG_RE = re.compile(r"^v\d{8}\.\d{2}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_URL_LINE = re.compile(r'^(?P<indent>[ \t]*)url[ \t]+"(?P<url>[^"]*)"', re.MULTILINE)
_TAG = re.compile(r'(?P<key>\btag:\s*)"(?P<value>[^"]*)"')
_REVISION = re.compile(r'(?P<key>\brevision:\s*)"(?P<value>[^"]*)"')
_USING = re.compile(r"\busing:")


def _statement(text: str) -> tuple[int, int, str]:
    """Span and text of the first ``url`` statement (up to the first line not ending in ',')."""
    match = _URL_LINE.search(text)
    if match is None:
        raise Fehler("Vorlage ohne url-Anweisung")
    start = match.start()
    end = text.find("\n", start)
    while end != -1 and text[start:end].rstrip().endswith(","):
        end = text.find("\n", end + 1)
    if end == -1:
        end = len(text)
    return start, end, text[start:end]


def get_source(text: str) -> tuple[str, str | None, str | None]:
    """Return ``(url, tag, revision)`` of the first ``url`` statement."""
    _, _, statement = _statement(text)
    url = _URL_LINE.search(statement)
    assert url is not None
    tag = _TAG.search(statement)
    revision = _REVISION.search(statement)
    return (
        url.group("url"),
        tag.group("value") if tag else None,
        revision.group("value") if revision else None,
    )


def set_source(text: str, url: str, tag: str, revision: str) -> str:
    """Replace url, tag and revision; a local path additionally gets ``using: :git``."""
    if not SOURCE_TAG_RE.match(tag):
        raise Fehler(f"Tag '{tag}' passt nicht zu vJJJJMMTT.NN")
    if not _REVISION_RE.match(revision):
        raise Fehler(f"revision '{revision}' ist kein 40-stelliger Commit-Hash")
    start, end, statement = _statement(text)
    if not _TAG.search(statement) or not _REVISION.search(statement):
        raise Fehler("Vorlage ohne tag: und revision: in der url-Anweisung")
    statement = _URL_LINE.sub(lambda m: f'{m.group("indent")}url "{url}"', statement, count=1)
    statement = _TAG.sub(lambda m: f'{m.group("key")}"{tag}"', statement, count=1)
    statement = _REVISION.sub(lambda m: f'{m.group("key")}"{revision}"', statement, count=1)
    if url.startswith("/") and not _USING.search(statement):
        statement = _add_using_git(statement)
    return text[:start] + statement + text[end:]


def _add_using_git(statement: str) -> str:
    lines = statement.split("\n")
    if len(lines) == 1:
        return _URL_LINE.sub(lambda m: f"{m.group(0)}, using: :git", statement, count=1)
    # multi-line: insert a table-aligned line before the tag line
    for number, line in enumerate(lines[1:], start=1):
        if _TAG.search(line):
            indent = line[: len(line) - len(line.lstrip())]
            lines.insert(number, f"{indent}using:    :git,")
            break
    return "\n".join(lines)


def set_try_source(text: str, url: str, revision: str, version: str) -> str:
    """Point the formula at a local checkout (``using: :git``, ``revision``, no ``tag:``)."""
    if not _REVISION_RE.match(revision):
        raise Fehler(f"revision '{revision}' ist kein 40-stelliger Commit-Hash")
    start, end, _ = _statement(text)
    match = _URL_LINE.search(text, start)
    assert match is not None
    indent = match.group("indent")
    replacement = (
        f'{indent}url "{url}", using: :git, revision: "{revision}"\n{indent}version "{version}"'
    )
    return text[:start] + replacement + text[end:]

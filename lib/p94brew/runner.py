"""Run external commands; replaceable in tests."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .cli import Fehler, Output


@dataclass
class Result:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class Runner:
    """Thin wrapper around ``subprocess.run`` with dry-run support."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        dry_run: bool = False,
        output: Output | None = None,
    ) -> None:
        self.env = dict(env) if env is not None else None
        self.dry_run = dry_run
        self.output = output

    def run(
        self,
        args: list[str],
        *,
        check: bool = False,
        capture: bool = True,
        cwd: str | Path | None = None,
        env_extra: Mapping[str, str] | None = None,
        input: str | None = None,  # noqa: A002 - mirrors subprocess.run
    ) -> Result:
        env = dict(self.env if self.env is not None else os.environ)
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            args,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            input=input,
            # A captured command is a probe and must not wait for a terminal.
            stdin=subprocess.DEVNULL if capture and input is None else None,
            check=False,
        )
        result = Result(list(args), proc.returncode, proc.stdout or "", proc.stderr or "")
        if check and result.returncode != 0:
            lines = result.stderr.strip().splitlines()
            last = lines[-1] if lines else "keine Fehlerausgabe"
            raise Fehler(f"{shlex.join(args)} endete mit {result.returncode}: {last}")
        return result

    def change(self, args: list[str], **kw) -> Result:
        """Like :meth:`run`, but only announce the command in dry-run mode."""
        if self.dry_run:
            if self.output is not None:
                self.output.info(f"würde ausführen: {shlex.join(args)}")
            return Result(list(args), 0, "", "")
        return self.run(args, **kw)


class FakeRunner(Runner):
    """Test double: records calls and answers from registered prefixes.

    The longest matching prefix wins; among equal ones the rule added last, so a test can override.
    Commands in ``passthrough`` run for real unless a rule matches them.
    """

    def __init__(self, *args, passthrough: tuple[str, ...] = (), **kw) -> None:
        super().__init__(*args, **kw)
        self.passthrough = passthrough
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []  # env_extra of each call, same order as calls
        self._rules: list[tuple[tuple[str, ...], Result]] = []

    def add(self, prefix: tuple[str, ...], result: Result) -> None:
        self._rules.append((prefix, result))

    def run(self, args: list[str], *, check: bool = False, **kw) -> Result:
        self.calls.append(list(args))
        self.envs.append(dict(kw.get("env_extra") or {}))
        best: Result | None = None
        best_len = -1
        for prefix, result in self._rules:
            if tuple(args[: len(prefix)]) == prefix and len(prefix) >= best_len:
                best, best_len = result, len(prefix)
        if best is None and Path(args[0]).name in self.passthrough:
            return Runner.run(self, args, check=check, **kw)
        result = (
            Result(list(args), best.returncode, best.stdout, best.stderr)
            if best is not None
            else Result(list(args), 0, "", "")
        )
        if check and result.returncode != 0:
            lines = result.stderr.strip().splitlines()
            last = lines[-1] if lines else "keine Fehlerausgabe"
            raise Fehler(f"{shlex.join(args)} endete mit {result.returncode}: {last}")
        return result

"""Paths and environment helpers.

``brew`` passes only ``HOMEBREW_*`` variables to external commands, so the user's
environment is restored from the ``HOMEBREW_<NAME>`` copies (Homebrew ``bin/brew:304-316``).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import MutableMapping
from pathlib import Path

DEFAULT_PREFIX = Path("/home/linuxbrew/.linuxbrew")

RESTORE_VARS = (
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_DATA_DIRS",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "TMPDIR",
    "NO_COLOR",
)

Environ = MutableMapping[str, str]


def _env(environ: Environ | None) -> Environ:
    return os.environ if environ is None else environ


def restore_user_env(environ: Environ | None = None) -> None:
    """Copy ``HOMEBREW_<NAME>`` to ``<NAME>`` where the latter is missing."""
    env = _env(environ)
    for name in RESTORE_VARS:
        if not env.get(name) and env.get(f"HOMEBREW_{name}"):
            env[name] = env[f"HOMEBREW_{name}"]
    run_dir = Path(f"/run/user/{os.getuid()}")
    if not env.get("XDG_RUNTIME_DIR") and run_dir.is_dir():
        env["XDG_RUNTIME_DIR"] = str(run_dir)
    bus = Path(env.get("XDG_RUNTIME_DIR", "")) / "bus"
    if not env.get("DBUS_SESSION_BUS_ADDRESS") and env.get("XDG_RUNTIME_DIR") and bus.exists():
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"


def brew_prefix(environ: Environ | None = None) -> Path:
    """Homebrew prefix: ``P94_BREW_PREFIX``, ``HOMEBREW_PREFIX`` or the Linux default."""
    env = _env(environ)
    return Path(env.get("P94_BREW_PREFIX") or env.get("HOMEBREW_PREFIX") or DEFAULT_PREFIX)


def brew_bin(environ: Environ | None = None) -> Path:
    env = _env(environ)
    return Path(env.get("HOMEBREW_BREW_FILE") or brew_prefix(env) / "bin/brew")


def home(environ: Environ | None = None) -> Path:
    env = _env(environ)
    return Path(env.get("HOME") or os.path.expanduser("~"))


def _xdg(name: str, fallback: str, environ: Environ | None) -> Path:
    env = _env(environ)
    return Path(env.get(name) or home(env) / fallback)


def xdg_config_home(environ: Environ | None = None) -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config", environ)


def xdg_data_home(environ: Environ | None = None) -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share", environ)


def xdg_state_home(environ: Environ | None = None) -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state", environ)


def xdg_cache_home(environ: Environ | None = None) -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache", environ)


def runtime_dir(environ: Environ | None = None) -> Path:
    env = _env(environ)
    if env.get("XDG_RUNTIME_DIR"):
        return Path(env["XDG_RUNTIME_DIR"])
    run_dir = Path(f"/run/user/{os.getuid()}")
    return run_dir if run_dir.is_dir() else Path(tempfile.gettempdir())

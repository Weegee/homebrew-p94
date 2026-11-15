"""Shared code of homebrew-p94 (tap weegee/p94)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
__version__ = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

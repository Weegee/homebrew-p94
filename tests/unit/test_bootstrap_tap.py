"""Tests of the tap step of p94-brew-bootstrap: GitHub by default, the folder only on request."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from .test_gitsrc import GIT_ENV, commit_file, git, make_repo

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "p94-brew-bootstrap"

FAKE_BREW = """#!/bin/sh
case "$1" in
    --repository) printf '%s\\n' "$FAKE_REPO" ;;
    *) printf '%s\\n' "$*" >>"$FAKE_LOG" ;;
esac
"""

HARNESS = """
source "$SCRIPT"
BREW=$FAKE_BREW TAP_URL=$FAKE_URL QUIET=1 DRY_RUN=$TEST_DRY TAP_FROM_PROJECT=$TEST_FROM
PROJECT_DIR=$FAKE_PROJECT
step_tap
printf '%s|%s\\n' "$STATE" "$RESULT"
"""


class TapStepTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # "GitHub" and the project folder are two repositories with the same content.
        self.github = make_repo(self.tmp / "github.git")
        commit_file(self.github, "Formula/a.rb", "a\n")
        self.project = self.tmp / "projekt"
        subprocess.run(
            ["git", "clone", "-q", str(self.github), str(self.project)],
            check=True,
            env=GIT_ENV | os.environ,
        )
        self.brew = self.tmp / "brew"
        self.brew.write_text(FAKE_BREW)
        self.brew.chmod(0o755)
        self.repo = self.tmp / "repo"
        self.tap = self.repo / "Library/Taps/weegee/homebrew-p94"
        self.log = self.tmp / "brew.log"
        self.log.touch()

    def clone_tap(self, origin: str) -> None:
        self.tap.parent.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "-q", origin, str(self.tap)], check=True, env=GIT_ENV | os.environ
        )

    def step(self, dry_run: bool, from_project: bool = False, url: str | None = None) -> str:
        env = {
            **os.environ,
            **GIT_ENV,
            "SCRIPT": str(SCRIPT),
            "FAKE_BREW": str(self.brew),
            "FAKE_REPO": str(self.repo),
            "FAKE_LOG": str(self.log),
            "FAKE_URL": url or str(self.github),
            "FAKE_PROJECT": str(self.project),
            "TEST_DRY": str(int(dry_run)),
            "TEST_FROM": str(int(from_project)),
        }
        done = subprocess.run(
            ["bash", "-c", HARNESS], capture_output=True, text=True, env=env, check=False
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def origin(self) -> str:
        return git(self.tap, "remote", "get-url", "origin")

    def test_fresh_dry_run_names_github_not_the_project(self):
        out = self.step(dry_run=True)
        self.assertEqual(out, f"würde|würde einbinden aus {self.github}")
        self.assertEqual(self.log.read_text(), "")

    def test_fresh_taps_from_github(self):
        out = self.step(dry_run=False)
        self.assertEqual(out, f"geändert|eingebunden aus {self.github}")
        self.assertEqual(
            self.log.read_text().splitlines(),
            [f"tap weegee/p94 {self.github}", "trust --tap weegee/p94"],
        )

    def test_fresh_from_project_taps_from_the_folder(self):
        out = self.step(dry_run=False, from_project=True)
        self.assertEqual(out, f"geändert|eingebunden aus {self.project}")
        self.assertIn(f"tap weegee/p94 {self.project}", self.log.read_text())

    def test_tap_on_github_stays_in_dry_run_and_run(self):
        self.clone_tap(str(self.github))
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                out = self.step(dry_run=dry_run)
                self.assertTrue(out.startswith("erledigt|schon eingebunden"), out)
                self.assertEqual(self.origin(), str(self.github))

    def test_url_spelling_is_not_a_difference(self):
        want = "https://github.com/Weegee/homebrew-p94.git"
        self.clone_tap(str(self.github))
        for origin in (
            want[:-4],
            want[:-4] + "/",
            "git@github.com:Weegee/homebrew-p94.git",
            "https://github.com/weegee/homebrew-p94",
        ):
            with self.subTest(origin=origin):
                git(self.tap, "remote", "set-url", "origin", origin)
                out = self.step(dry_run=True, url=want)
                self.assertTrue(out.startswith("erledigt|schon eingebunden"), out)

    def test_tap_on_project_is_reported_and_switched_to_github(self):
        self.clone_tap(str(self.project))
        out = self.step(dry_run=True)
        self.assertEqual(
            out, f"würde|würde origin umstellen auf {self.github} (bisher {self.project})"
        )
        self.assertEqual(self.origin(), str(self.project))
        out = self.step(dry_run=False)
        self.assertEqual(out, f"geändert|origin umgestellt auf {self.github}")
        self.assertEqual(self.origin(), str(self.github))

    def test_from_project_keeps_a_tap_on_the_project(self):
        self.clone_tap(str(self.project))
        out = self.step(dry_run=True, from_project=True)
        self.assertTrue(out.startswith("erledigt|schon eingebunden"), out)

    def test_from_project_switches_a_tap_on_github(self):
        self.clone_tap(str(self.github))
        out = self.step(dry_run=False, from_project=True)
        self.assertEqual(out, f"geändert|origin umgestellt auf {self.project}")
        self.assertEqual(self.origin(), str(self.project))


if __name__ == "__main__":
    unittest.main()

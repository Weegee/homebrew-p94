import io
import json
import tempfile
import unittest
from pathlib import Path

from p94brew import formula_try
from p94brew.cli import Fehler, Output
from p94brew.runner import FakeRunner, Result

from .test_gitsrc import commit_file, git, make_repo
from .test_sync import TEMPLATE

BREW = "brew"


def make_output():
    err = io.StringIO()
    out = io.StringIO()
    return (
        Output(formula_try.PROG, color="never", out=out, err=err, env={"LANG": "C.UTF-8"}),
        out,
        err,
    )


class TryFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_repo(self.root / "p94-demo")
        commit_file(self.repo, "VERSION", "20261104.01\n")
        commit_file(self.repo, "packaging/homebrew/p94-demo.rb", TEMPLATE)
        self.commit = git(self.repo, "rev-parse", "HEAD")
        self.tap = self.root / "tap"
        self.runner = FakeRunner(passthrough=("git",))
        self.runner.add((BREW, "tap"), Result([], 0, "homebrew/core\n", ""))
        self.runner.add(
            (BREW, "--repository", formula_try.TRY_TAP), Result([], 0, f"{self.tap}\n", "")
        )

    def run_try(self, formulae=(), rev=None, keep=False):
        output, out, err = make_output()
        rc = formula_try.run_try(self.repo, formulae, rev, keep, self.runner, output, BREW)
        return rc, out.getvalue(), err.getvalue()

    def brew_calls(self):
        return [c[1:] for c in self.runner.calls if c[0] == BREW]

    def verbs(self):
        return [c[0] for c in self.brew_calls()]


class RunTryTest(TryFixture):
    def test_steps_in_order_and_cleanup(self):
        rc, out, _ = self.run_try()
        self.assertEqual(rc, 0, out)
        full = f"{formula_try.TRY_TAP}/p94-demo"
        calls = self.brew_calls()
        self.assertIn(["tap-new", "--no-git", formula_try.TRY_TAP], calls)
        wanted = [
            ["style", "--formula", full],
            ["audit", "--formula", full],
            ["install", "--build-from-source", full],
            ["test", full],
            ["p94-link", "--dry-run", "p94-demo"],
            ["uninstall", "--force", full],
            ["untap", formula_try.TRY_TAP],
            ["untrust", "--tap", formula_try.TRY_TAP],
        ]
        positions = [calls.index(c) for c in wanted]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(calls.index(["trust", "--tap", formula_try.TRY_TAP]), positions[0])
        self.assertEqual(out.count("✓"), 5)

    def test_formula_points_at_the_local_commit(self):
        self.run_try()
        text = (self.tap / "Formula/p94-demo.rb").read_text()
        self.assertIn(f'url "{self.repo}", using: :git, revision: "{self.commit}"', text)
        self.assertIn('version "20261104.01"', text)
        self.assertNotIn("tag:", text)

    def test_rev_selects_an_older_commit(self):
        commit_file(self.repo, "VERSION", "20261104.02\n")
        rc, _, _ = self.run_try(rev=self.commit)
        self.assertEqual(rc, 0)
        text = (self.tap / "Formula/p94-demo.rb").read_text()
        self.assertIn(f'revision: "{self.commit}"', text)
        self.assertIn('version "20261104.01"', text)

    def test_failure_stops_the_formula_but_still_cleans_up(self):
        self.runner.add((BREW, "audit"), Result([], 1, "", "p94-demo: Befund 1\nBefund 2"))
        rc, out, err = self.run_try()
        self.assertEqual(rc, 1)
        self.assertIn("✗ p94-demo: brew audit", out)
        self.assertIn("Befund 2", err)
        self.assertNotIn("install", self.verbs())
        self.assertIn("untap", self.verbs())
        self.assertIn("untrust", self.verbs())

    def test_keep_leaves_tap_and_formulae(self):
        rc, _, err = self.run_try(keep=True)
        self.assertEqual(rc, 0)
        for verb in ("uninstall", "untap", "untrust"):
            self.assertNotIn(verb, self.verbs())
        self.assertIn(f"brew untap {formula_try.TRY_TAP}", err)

    def test_cleanup_after_a_setup_failure(self):
        self.runner.add((BREW, "trust"), Result([], 1, "", "kaputt"))
        with self.assertRaises(Fehler):
            self.run_try()
        self.assertIn("untap", self.verbs())

    def test_no_cleanup_when_the_tap_was_not_created(self):
        self.runner.add((BREW, "tap-new"), Result([], 1, "", "kaputt"))
        with self.assertRaises(Fehler):
            self.run_try()
        self.assertNotIn("untap", self.verbs())

    def test_existing_try_tap_is_an_error(self):
        self.runner.add((BREW, "tap"), Result([], 0, f"{formula_try.TRY_TAP}\n", ""))
        with self.assertRaises(Fehler) as ctx:
            self.run_try()
        self.assertIn(f"brew untap {formula_try.TRY_TAP}", str(ctx.exception))
        self.assertNotIn("tap-new", self.verbs())

    def test_formula_installed_from_another_tap(self):
        self.runner.add(
            (BREW, "list", "--formula", "--versions", "p94-demo"), Result([], 0, "p94-demo 1\n", "")
        )
        info = json.dumps({"formulae": [{"tap": "weegee/p94"}]})
        self.runner.add((BREW, "info"), Result([], 0, info, ""))
        with self.assertRaises(Fehler) as ctx:
            self.run_try()
        self.assertEqual(
            str(ctx.exception),
            "p94-demo ist schon aus weegee/p94 installiert; erst brew uninstall p94-demo",
        )
        self.assertNotIn("tap-new", self.verbs())

    def test_missing_version_file(self):
        repo = make_repo(self.root / "no-version")
        commit_file(repo, "packaging/homebrew/p94-demo.rb", TEMPLATE)
        output, _, _ = make_output()
        with self.assertRaises(Fehler) as ctx:
            formula_try.run_try(repo, (), None, False, self.runner, output, BREW)
        self.assertIn("VERSION fehlt in", str(ctx.exception))

    def test_unknown_formula_and_missing_templates(self):
        with self.assertRaises(Fehler) as ctx:
            self.run_try(formulae=["nope"])
        self.assertIn("Vorlage nope.rb fehlt", str(ctx.exception))
        empty = make_repo(self.root / "empty")
        commit_file(empty, "VERSION", "1\n")
        output, _, _ = make_output()
        with self.assertRaises(Fehler) as ctx:
            formula_try.run_try(empty, (), None, False, self.runner, output, BREW)
        self.assertIn("keine Vorlage unter packaging/homebrew/", str(ctx.exception))

    def test_not_a_repository(self):
        output, _, _ = make_output()
        with self.assertRaises(Fehler) as ctx:
            formula_try.run_try(self.root / "x", (), None, False, self.runner, output, BREW)
        self.assertIn("kein Git-Repository", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

import contextlib
import fcntl
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p94brew import sync
from p94brew.cli import Fehler
from p94brew.runner import FakeRunner, Result

from .steamos_fixture import desc_text, make_system
from .test_gitsrc import GIT_ENV, commit_file, git, make_repo

TEMPLATE = """\
class P94Demo < Formula
  desc "Demo"
  homepage "https://example.org"
  url "https://github.com/example/p94-demo.git",
      tag:      "v00000000.00",
      revision: "0000000000000000000000000000000000000000"
  license "GPL-3.0-or-later"
end
"""


class SyncFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        # source project with a template and a tag
        self.src = make_repo(self.root / "p94-demo")
        commit_file(self.src, "packaging/homebrew/p94-demo.rb", TEMPLATE)
        git(self.src, "tag", "-a", "-m", "r", "v20261104.01")
        self.commit1 = git(self.src, "rev-parse", "HEAD")
        # the project that is the tap, and the tap clone
        self.proj = make_repo(self.root / "project")
        (self.proj / "Formula").mkdir()
        (self.proj / "Formula/.gitkeep").write_text("")
        (self.proj / "p94-sync.toml").write_text(
            f'[[source]]\nname = "p94-demo"\nurl = "{self.src}"\n\n'
            '[[source]]\nname = "gone"\nurl = "' + str(self.root / "gone") + '"\n\n'
            '[[source]]\nname = "untagged"\nurl = "' + str(self.root / "untagged") + '"\n'
        )
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-q", "-m", "init")
        self.untagged = make_repo(self.root / "untagged")
        commit_file(self.untagged, "README", "x\n")
        self.tap = self.root / "tap"
        git(self.root, "clone", "-q", str(self.proj), str(self.tap))
        self.cache = self.root / "cache"
        self.environ = {
            **GIT_ENV,
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_RUNTIME_DIR": str(self.root / "run"),
            "HOME": str(self.root),
            "TERM": "dumb",
            "LANG": "de_DE.UTF-8",
        }
        (self.root / "run").mkdir()
        self.patch = mock.patch.dict(os.environ, self.environ)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def runner(self, installed=False, audit_fails=False, dry_run=False):
        fake = FakeRunner(passthrough=("git",), dry_run=dry_run)
        fake.add(("brew", "--repository"), Result([], 0, f"{self.tap}\n", ""))
        if installed:
            fake.add(("brew", "list"), Result([], 0, "p94-demo 20261101.01\n", ""))
        else:
            fake.add(("brew", "list"), Result([], 1, "", "Error: No such keg"))
        if audit_fails:
            fake.add(("brew", "audit"), Result([], 1, "p94-demo: * bad desc\n", ""))
        return fake

    def run_sync(self, *argv, **kw):
        system = kw.pop("system", None)
        runner = kw.pop("runner", None) or self.runner(**kw)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main(list(argv), runner=runner, system=system)
        return code, out.getvalue(), err.getvalue(), runner

    def project_log(self):
        return git(self.proj, "log", "--format=%s").splitlines()


class SyncTest(SyncFixture):
    def test_new_formula_is_committed_and_tap_fast_forwarded(self):
        code, out, err, runner = self.run_sync()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.project_log()[0], "p94-demo 20261104.01")
        formula = (self.proj / "Formula/p94-demo.rb").read_text()
        self.assertIn(f'url "{self.src}"', formula)
        self.assertIn("using:    :git", formula)
        self.assertIn('tag:      "v20261104.01"', formula)
        self.assertIn(f'revision: "{self.commit1}"', formula)
        self.assertEqual((self.tap / "Formula/p94-demo.rb").read_text(), formula)
        self.assertEqual(git(self.tap, "status", "--porcelain"), "")
        self.assertIn(["brew", "style", "--formula", "weegee/p94/p94-demo"], runner.calls)
        self.assertIn(["brew", "audit", "--formula", "weegee/p94/p94-demo"], runner.calls)
        row = [line.split() for line in out.splitlines() if line.startswith("p94-demo")][0]
        self.assertEqual(row, ["p94-demo", "p94-demo", "-", "20261104.01", "neu"])
        self.assertIn("nicht installiert; installieren: brew install", err)

    def test_second_run_is_current(self):
        self.run_sync()
        git(self.tap, "pull", "-q", "--ff-only")
        code, out, _, _ = self.run_sync()
        self.assertEqual(code, 0)
        self.assertIn("aktuell", out)
        self.assertEqual(len([m for m in self.project_log() if m.startswith("p94-demo")]), 1)

    def test_new_tag_updates_formula(self):
        self.run_sync()
        commit_file(self.src, "packaging/homebrew/p94-demo.rb", TEMPLATE + "# v2\n")
        git(self.src, "tag", "v20261105.01")
        code, out, _, _ = self.run_sync()
        self.assertEqual(code, 0)
        self.assertEqual(self.project_log()[0], "p94-demo 20261105.01")
        self.assertIn("20261104.01", out)
        self.assertIn("20261105.01", out)
        self.assertIn("aktualisiert", out)

    def test_audit_failure_leaves_no_commit_and_no_file(self):
        code, out, err, _ = self.run_sync(audit_fails=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.project_log(), ["init"])
        self.assertFalse((self.tap / "Formula/p94-demo.rb").exists())
        self.assertFalse((self.proj / "Formula/p94-demo.rb").exists())
        self.assertIn("Fehler: style oder audit meldet Befunde", out)
        self.assertIn("bad desc", err)

    def test_missing_source_and_untagged_source_are_skipped(self):
        code, out, _, _ = self.run_sync()
        self.assertEqual(code, 0)
        self.assertIn("übersprungen: Repository nicht gefunden", out)
        self.assertIn("übersprungen: kein Tag vJJJJMMTT.NN", out)

    def test_tag_without_template(self):
        commit_file(self.untagged, "README", "y\n")
        git(self.untagged, "tag", "v20261104.01")
        code, out, _, _ = self.run_sync()
        self.assertEqual(code, 0)
        self.assertIn("übersprungen: keine Vorlage in v20261104.01", out)

    def test_uncommitted_formula_changes_in_project(self):
        (self.proj / "Formula/other.rb").write_text("# draft\n")
        with self.assertRaises(Fehler) as ctx:
            self.run_sync()
        self.assertIn("uncommittete Änderungen", str(ctx.exception))

    def test_wrong_branch_in_project(self):
        git(self.proj, "switch", "-q", "-c", "other")
        with self.assertRaises(Fehler) as ctx:
            self.run_sync()
        self.assertIn("steht auf Zweig other", str(ctx.exception))

    def test_dry_run_writes_nothing(self):
        code, out, _, runner = self.run_sync("--dry-run", dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("würde hinzufügen", out)
        self.assertEqual(self.project_log(), ["init"])
        self.assertFalse((self.tap / "Formula/p94-demo.rb").exists())
        self.assertFalse(any(c[:2] == ["brew", "upgrade"] for c in runner.calls))

    def test_dry_run_tolerates_dirty_project(self):
        (self.proj / "Formula/other.rb").write_text("# draft\n")
        code, _, _, _ = self.run_sync("--dry-run", dry_run=True)
        self.assertEqual(code, 0)

    def test_installed_formula_is_upgraded(self):
        _, _, err, runner = self.run_sync(installed=True)
        self.assertIn(["brew", "upgrade", "weegee/p94/p94-demo"], runner.calls)
        self.assertIn("Nächster Schritt: brew p94-link", err)

    def test_no_upgrade(self):
        _, _, _, runner = self.run_sync("--no-upgrade", installed=True)
        self.assertFalse(any(c[:2] == ["brew", "upgrade"] for c in runner.calls))

    def test_source_filter(self):
        code, out, _, _ = self.run_sync("p94-demo")
        self.assertEqual(code, 0)
        self.assertNotIn("untagged", out)
        self.assertNotIn("gone", out)

    def test_lock_held(self):
        path = Path(self.root / "run" / "p94-sync.lock")
        with open(path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with self.assertRaises(Fehler) as ctx:
                self.run_sync()
        self.assertIn("läuft schon", str(ctx.exception))


SYSROOT_LIST = """\
formula = "steamos-sysroot"
desc = "C- und Kernel-Header aus SteamOS"
gcc_links = true

[[package]]
name = "glibc"
headers = true

[[package]]
name = "linux-api-headers"
headers = true
"""

TOOLS_LIST = """\
formula = "steamos-tools"
desc = "Werkzeuge aus dem SteamOS-Spiegel"

[[package]]
name = "ethtool"
bin = ["ethtool"]
test = ["ethtool", "--version"]
"""


class SteamosSyncTest(SyncFixture):
    def setUp(self):
        super().setUp()
        (self.proj / "steamos").mkdir()
        (self.proj / "steamos/steamos-sysroot.toml").write_text(SYSROOT_LIST)
        (self.proj / "steamos/steamos-tools.toml").write_text(TOOLS_LIST)
        config = (self.proj / "p94-sync.toml").read_text()
        config += (
            '\n[steamos]\nlists = ["steamos/steamos-sysroot.toml", "steamos/steamos-tools.toml"]\n'
        )
        (self.proj / "p94-sync.toml").write_text(config)
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-q", "-m", "lists")
        git(self.tap, "pull", "-q", "--ff-only")
        self.system = self.make_system()

    def make_system(self, glibc_local="2.43-1"):
        sync_dbs = {
            "core-3.9": [
                desc_text("glibc", "2.43-1", sha="a" * 64, depends=["linux-api-headers"]),
                desc_text("linux-api-headers", "7.1-1", sha="b" * 64),
            ],
            "extra-3.9": [
                desc_text("ethtool", "1:7.1-1", sha="c" * 64, depends=["glibc", "libmnl"])
            ],
        }
        local = [
            desc_text("glibc", glibc_local),
            desc_text("linux-api-headers", "7.1-1"),
            desc_text("libmnl", "1.0.5-2"),
        ]
        return make_system(self.root / "sys", sync_dbs, local)

    def test_steamos_only_creates_both_formulae(self):
        code, out, err, runner = self.run_sync("--steamos-only", system=self.system)
        self.assertEqual(code, 0, err)
        subjects = self.project_log()
        self.assertIn("steamos-sysroot 20261023.100", subjects)
        self.assertIn("steamos-tools 20261023.100", subjects)
        text = (self.tap / "Formula/steamos-sysroot.rb").read_text()
        self.assertIn("class SteamosSysroot < Formula", text)
        self.assertEqual(text.count("using: :nounzip"), 2)
        self.assertFalse(any(c[:2] == ["git", "ls-remote"] for c in runner.calls))
        self.assertIn("steamos/steamos-sysroot.toml", out)
        self.assertIn("neu", out)
        self.assertIn(["brew", "style", "--formula", "weegee/p94/steamos-tools"], runner.calls)

    def test_second_run_is_current(self):
        self.run_sync("--steamos-only", system=self.system)
        git(self.tap, "pull", "-q", "--ff-only")
        code, out, _, _ = self.run_sync("--steamos-only", system=self.system)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("aktuell"), 2)

    def test_dry_run(self):
        code, out, _, _ = self.run_sync(
            "--steamos-only", "--dry-run", system=self.system, dry_run=True
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.count("würde hinzufügen"), 2)
        self.assertEqual(git(self.proj, "log", "--format=%s").splitlines()[0], "lists")

    def test_no_steamos_skips_the_lists(self):
        _, out, _, _ = self.run_sync("--no-steamos")
        self.assertNotIn("steamos-", out)

    def test_default_run_does_both(self):
        code, out, _, _ = self.run_sync(system=self.system)
        self.assertEqual(code, 0)
        self.assertIn("p94-demo", out)
        self.assertIn("steamos-tools", out)

    def test_flags_exclude_each_other(self):
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
            self.run_sync("--steamos-only", "--no-steamos", system=self.system)
        self.assertEqual(ctx.exception.code, 2)

    def test_version_conflict_is_an_error_row(self):
        system = self.make_system(glibc_local="2.42-1")
        code, out, _, _ = self.run_sync("--steamos-only", system=system)
        self.assertEqual(code, 1)
        self.assertIn("Fehler: glibc: Paketdatenbank hat 2.43-1, das System 2.42-1", out)
        self.assertFalse((self.tap / "Formula/steamos-sysroot.rb").exists())


class ProjectDirTest(SyncFixture):
    """The tap's origin is a URL, so the project dir comes from elsewhere."""

    def setUp(self):
        super().setUp()
        git(self.tap, "remote", "set-url", "origin", "https://github.com/weegee/homebrew-p94")
        os.environ.pop(sync.PROJECT_ENV, None)

    def test_env_names_the_project(self):
        with mock.patch.dict(os.environ, {sync.PROJECT_ENV: str(self.proj)}):
            info = sync.tap_info("weegee/p94", self.runner())
        self.assertEqual(info.source_repo, self.proj)
        self.assertEqual(info.path, self.tap)

    def test_default_dir_is_used_when_it_is_a_repo(self):
        default = self.root / sync.PROJECT_DEFAULT
        default.parent.mkdir(parents=True)
        git(self.root, "clone", "-q", str(self.proj), str(default))
        info = sync.tap_info("weegee/p94", self.runner())
        self.assertEqual(info.source_repo, default)

    def test_url_origin_without_project_is_an_error(self):
        with self.assertRaises(Fehler) as ctx:
            sync.tap_info("weegee/p94", self.runner())
        text = str(ctx.exception)
        self.assertIn("origin ist https://github.com/weegee/homebrew-p94", text)
        self.assertIn(f"export {sync.PROJECT_ENV}=PFAD", text)

    def test_env_without_repo_is_an_error(self):
        with mock.patch.dict(os.environ, {sync.PROJECT_ENV: str(self.root / "nirgends")}):
            with self.assertRaises(Fehler) as ctx:
                sync.tap_info("weegee/p94", self.runner())
        self.assertIn("kein Git-Repository", str(ctx.exception))

    def test_steamos_only_config_runs_without_sources(self):
        (self.tap / "p94-sync.toml").write_text("[steamos]\nlists = []\n")
        with mock.patch.dict(os.environ, {sync.PROJECT_ENV: str(self.proj)}):
            code, _, err, _ = self.run_sync()
        self.assertEqual(code, 0, err)


class ConfigTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p94-sync.toml"
            path.write_text(text)
            return sync.load_config(path)

    def test_source_and_lists(self):
        sources, lists = self.load(
            '[[source]]\nname = "a"\nurl = "https://example.org/a.git"\n'
            '[steamos]\nlists = ["x.toml"]\n'
        )
        self.assertEqual(sources[0].url, "https://example.org/a.git")
        self.assertEqual(lists, ["x.toml"])

    def test_no_sources_is_fine(self):
        sources, lists = self.load('[steamos]\nlists = ["x.toml"]\n')
        self.assertEqual(sources, [])
        self.assertEqual(lists, ["x.toml"])

    def test_source_without_url(self):
        with self.assertRaises(Fehler) as ctx:
            self.load('[[source]]\nname = "a"\n')
        self.assertIn("[[source]] a ohne url", str(ctx.exception))

    def test_unknown_key(self):
        with self.assertRaises(Fehler) as ctx:
            self.load('[[source]]\nname = "a"\nbogus = 1\n')
        self.assertIn("unbekannter Schlüssel 'bogus' in [[source]] a", str(ctx.exception))

    def test_repo_file_parses(self):
        root = Path(__file__).resolve().parents[2]
        sources, lists = sync.load_config(root / "p94-sync.toml")
        self.assertEqual(sources, [])
        self.assertEqual(len(lists), 3)


if __name__ == "__main__":
    unittest.main()

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p94brew import pacmandb, toolchain
from p94brew.cli import Fehler, Output
from p94brew.runner import FakeRunner, Result

BREW = "/home/linuxbrew/.linuxbrew/bin/brew"
DUMPSPECS = "*asm:\n%{m32:--32} %o foo\n\n*link:\n%{shared} %o bar\n"
PACKAGES = [
    {"name": "glibc", "version": "2.43+r37-1"},
    {"name": "linux-api-headers", "version": "7.1-1"},
]


def local_db(glibc="2.43+r37-1", headers="7.1-1"):
    return {
        "glibc": pacmandb.PkgDesc("glibc", glibc, repo="local"),
        "linux-api-headers": pacmandb.PkgDesc("linux-api-headers", headers, repo="local"),
    }


def make_output():
    err = io.StringIO()
    out = io.StringIO()
    return (
        Output(toolchain.PROG, color="never", out=out, err=err, env={"LANG": "C.UTF-8"}),
        out,
        err,
    )


class Tree(unittest.TestCase):
    """A throw-away Homebrew prefix with gcc 16, the sysroot and a crt folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.prefix = self.root / "brew"
        self.crt = self.root / "usr-lib"
        self.crt.mkdir()
        for name in ("Scrt1.o", "crt1.o", "crti.o", "crtn.o", "libc.so"):
            (self.crt / name).write_text("")
        keg = self.prefix / "Cellar/gcc/16.2.0"
        (keg / "bin").mkdir(parents=True)
        for tool in ("gcc", "g++", "cpp"):
            (keg / f"bin/{tool}-16").write_text("")
        self.libgcc = keg / "lib/gcc/current/gcc/x86_64-pc-linux-gnu/16"
        self.libgcc.mkdir(parents=True)
        (self.prefix / "opt").mkdir()
        (self.prefix / "opt/gcc").symlink_to(keg)
        self.opt_libgcc = self.prefix / "opt/gcc/lib/gcc/current/gcc/x86_64-pc-linux-gnu/16"
        sysroot = self.prefix / "opt/steamos-sysroot"
        (sysroot / "share/steamos-sysroot").mkdir(parents=True)
        (sysroot / "share/steamos-sysroot/packages.json").write_text(json.dumps(PACKAGES))
        (sysroot / "libexec/sysroot/usr/include").mkdir(parents=True)
        (self.prefix / "bin").mkdir()
        for name, tool in toolchain.COMPILER_LINKS.items():
            (self.prefix / "bin" / name).symlink_to(self.prefix / "opt/gcc/bin" / f"{tool}-16")
        (self.prefix / "lib").mkdir()
        (self.prefix / "lib/ld.so").write_text("")

    def runner(self, pinned="gcc\n", sysroot="steamos-sysroot 20261023.100\n"):
        runner = FakeRunner()
        triple = toolchain.TRIPLE
        libgcc_file = (
            f"{self.prefix}/Cellar/gcc/16.2.0/bin/../lib/gcc/current/gcc/{triple}/16/libgcc.a"
        )
        runner.add(
            (f"{self.prefix}/opt/gcc/bin/gcc-16", "-print-libgcc-file-name"),
            Result([], 0, libgcc_file + "\n", ""),
        )
        runner.add(
            (f"{self.prefix}/opt/gcc/bin/gcc-16", "-dumpspecs"), Result([], 0, DUMPSPECS, "")
        )
        runner.add((BREW, "list", "--pinned"), Result([], 0, pinned, ""))
        runner.add((BREW, "list", "--versions", "steamos-sysroot"), Result([], 0, sysroot, ""))
        return runner

    def brew_env(self):
        return mock.patch.object(toolchain.env, "brew_bin", return_value=Path(BREW))


class PureTest(unittest.TestCase):
    prefix = Path("/home/linuxbrew/.linuxbrew")

    def test_render_specs(self):
        out = toolchain.render_specs(DUMPSPECS, self.prefix)
        self.assertEqual(out.count(" %o %(homebrew_rpath) "), 2)
        self.assertNotIn(" %o foo", out)
        self.assertTrue(out.startswith(DUMPSPECS.replace(" %o ", " %o %(homebrew_rpath) ")))
        self.assertIn(toolchain.specs_addition(self.prefix), out)
        self.assertNotIn("\n\n\n", out)
        self.assertNotIn("\n\n\n", toolchain.render_specs(DUMPSPECS + "\n\n", self.prefix))

    def test_specs_addition_is_exact(self):
        include = "/home/linuxbrew/.linuxbrew/opt/steamos-sysroot/libexec/sysroot/usr/include"
        expected = (
            "*cpp_unique_options:\n"
            "+ -isysroot /home/linuxbrew/.linuxbrew/nonexistent"
            f" -idirafter /home/linuxbrew/.linuxbrew/include -idirafter {include}\n"
            "\n*link_libgcc:\n"
            "+ -L/home/linuxbrew/.linuxbrew/lib/gcc/current -L/home/linuxbrew/.linuxbrew/lib\n"
            "\n*link:\n"
            "+ --dynamic-linker /home/linuxbrew/.linuxbrew/lib/ld.so"
            " -rpath /home/linuxbrew/.linuxbrew/lib/gcc/current\n"
            "\n*homebrew_rpath:\n"
            "-rpath /home/linuxbrew/.linuxbrew/lib\n"
            "\n"
        )
        self.assertEqual(toolchain.specs_addition(self.prefix), expected)

    def test_render_specs_adds_missing_newline(self):
        self.assertIn("x\n\n*cpp_unique_options:", toolchain.render_specs("x", self.prefix))

    def test_clang_cfg(self):
        gcc = toolchain.Gcc(16, Path("/d"), Path("/c/l"), Path("/p/opt/gcc/lib/16"))
        lines = toolchain.clang_cfg(self.prefix, gcc).splitlines()
        self.assertEqual(
            lines,
            [
                toolchain.MARKER,
                "-idirafter /home/linuxbrew/.linuxbrew/include",
                "-idirafter /home/linuxbrew/.linuxbrew/opt/steamos-sysroot"
                "/libexec/sysroot/usr/include",
                "--gcc-install-dir=/p/opt/gcc/lib/16",
                "-L/home/linuxbrew/.linuxbrew/lib/gcc/current",
                "-Wl,-rpath,/home/linuxbrew/.linuxbrew/lib/gcc/current",
            ],
        )


class FindGccTest(Tree):
    def test_find_gcc(self):
        gcc = toolchain.find_gcc(self.prefix, self.runner())
        self.assertEqual(gcc.major, 16)
        self.assertEqual(gcc.driver, self.prefix / "opt/gcc/bin/gcc-16")
        self.assertEqual(gcc.libgcc_dir, self.libgcc)
        self.assertEqual(gcc.opt_libgcc_dir, self.opt_libgcc)

    def test_highest_major_wins(self):
        (self.prefix / "Cellar/gcc/16.2.0/bin/gcc-17").write_text("")
        runner = self.runner()
        runner.add(
            (f"{self.prefix}/opt/gcc/bin/gcc-17", "-print-libgcc-file-name"),
            Result([], 0, f"{self.prefix}/Cellar/gcc/16.2.0/lib/gcc/x/17/libgcc.a\n", ""),
        )
        self.assertEqual(toolchain.find_gcc(self.prefix, runner).major, 17)

    def test_broken_specs_fall_back_to_the_homebrew_layout(self):
        runner = FakeRunner()
        runner.add(
            (f"{self.prefix}/opt/gcc/bin/gcc-16",), Result([], 1, "", "specs file malformed")
        )
        gcc = toolchain.find_gcc(self.prefix, runner)
        self.assertEqual(gcc.libgcc_dir, self.libgcc)
        self.assertEqual(gcc.opt_libgcc_dir, self.opt_libgcc)

    def test_none_without_gcc(self):
        self.assertIsNone(toolchain.find_gcc(self.root / "empty", self.runner()))


class ChecksTest(Tree):
    def checks(self, db=None, runner=None):
        with self.brew_env():
            return toolchain.run_checks(
                self.prefix, runner or self.runner(), db or local_db(), self.crt
            )

    def prepare_setup(self):
        out, _, _ = make_output()
        with self.brew_env():
            toolchain.setup(self.prefix, self.runner(), out, False, self.crt, local_db())

    def test_missing_setup_is_reported(self):
        by_label = {c.label: c for c in self.checks()}
        self.assertFalse(by_label["specs-Datei ohne SteamOS-Header"].ok)
        self.assertEqual(
            by_label["specs-Datei ohne SteamOS-Header"].hint, "brew p94-toolchain setup"
        )

    def test_all_green_after_setup(self):
        self.prepare_setup()
        failed = [c for c in self.checks() if c.ok is False]
        self.assertEqual(failed, [])

    def test_header_mismatch_text(self):
        labels = [c.label for c in self.checks(db=local_db(glibc="2.44-1"))]
        self.assertIn(
            "glibc-Header 2.43+r37-1 passen nicht zu glibc 2.44-1 im System. "
            "Erneuern: brew p94-sync",
            labels,
        )

    def test_header_match_text(self):
        labels = [c.label for c in self.checks()]
        self.assertIn(
            "Header passen zum System (glibc 2.43+r37-1, linux-api-headers 7.1-1)", labels
        )

    def test_gcc_not_pinned(self):
        checks = self.checks(runner=self.runner(pinned="\n"))
        unpinned = [c for c in checks if c.label == "gcc ist nicht angeheftet"]
        self.assertEqual(unpinned[0].hint, "brew pin gcc")

    def test_sysroot_missing(self):
        checks = self.checks(runner=self.runner(sysroot=""))
        missing = [c for c in checks if c.label == "steamos-sysroot ist nicht installiert"]
        self.assertEqual(missing[0].hint, "brew install weegee/p94/steamos-sysroot")

    def test_gcc_missing_stops_early(self):
        with self.brew_env():
            checks = toolchain.run_checks(self.root / "none", self.runner(), local_db(), self.crt)
        self.assertEqual(checks[0].hint, "brew install --skip-post-install gcc")
        self.assertFalse(any(c.label.startswith("Probe") for c in checks))

    def test_wrong_compiler_link(self):
        (self.prefix / "bin/cc").unlink()
        (self.prefix / "bin/cc").symlink_to(self.prefix / "opt/gcc/bin/g++-16")
        wrong = [c for c in self.checks() if "zeigen nicht auf gcc 16" in c.label]
        self.assertEqual(wrong[0].label, "cc zeigen nicht auf gcc 16")
        self.assertEqual(wrong[0].hint, "brew reinstall weegee/p94/steamos-sysroot")

    def test_clang_config_checked_only_with_clang(self):
        labels = [(c.ok, c.label) for c in self.checks()]
        self.assertIn((None, "clang-Konfiguration: clang nicht installiert"), labels)
        clang = self.prefix / "opt/llvm/bin/clang"
        clang.parent.mkdir(parents=True)
        clang.write_text("")
        bad = [c for c in self.checks() if c.label.startswith("clang-Konfiguration fehlt")]
        self.assertEqual(bad[0].hint, "brew p94-toolchain setup")

    def test_outdated_clang_config_is_reported(self):
        self.prepare_setup()
        clang = self.prefix / "opt/llvm/bin/clang"
        clang.parent.mkdir(parents=True)
        clang.write_text("")
        out, _, _ = make_output()
        with self.brew_env():
            toolchain.setup(self.prefix, self.runner(), out, False, self.crt, local_db())
        self.assertEqual([c for c in self.checks() if c.ok is False], [])
        cfg = self.prefix / "etc/clang/clang++.cfg"
        cfg.write_text(cfg.read_text().replace("-L", "-X"))
        bad = [c for c in self.checks() if c.label.startswith("clang-Konfiguration fehlt")]
        self.assertIn("clang++.cfg", bad[0].label)

    def test_probe_failure_shows_compiler_tail(self):
        runner = self.runner()
        err = "\n".join(f"zeile {i}" for i in range(9))
        runner.add((f"{self.prefix}/bin/cc",), Result([], 1, "", err))
        probe = [c for c in self.checks(runner=runner) if c.label.startswith("Probe: C mit cc")]
        self.assertFalse(probe[0].ok)
        self.assertEqual(probe[0].detail.splitlines(), [f"zeile {i}" for i in range(4, 9)])


class SetupTest(Tree):
    def run_setup(self, dry_run=False, runner=None):
        out, stdout, stderr = make_output()
        with self.brew_env():
            rc = toolchain.setup(
                self.prefix, runner or self.runner(), out, dry_run, self.crt, local_db()
            )
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_setup_writes_specs_and_links(self):
        rc, stdout, _ = self.run_setup()
        self.assertEqual(rc, 0, stdout)
        specs = (self.libgcc / "specs").read_text()
        self.assertEqual((self.libgcc / "specs.orig").read_text(), DUMPSPECS)
        self.assertIn(str(toolchain.sysroot_include(self.prefix)), specs)
        self.assertIn("%o %(homebrew_rpath)", specs)
        for name in ("Scrt1.o", "crt1.o", "crti.o", "crtn.o"):
            self.assertEqual((self.libgcc / name).resolve(), (self.crt / name).resolve())
        self.assertFalse((self.libgcc / "libc.so").exists())

    def test_setup_is_idempotent(self):
        self.run_setup()
        first = (self.libgcc / "specs").read_text()
        rc, _, _ = self.run_setup()
        self.assertEqual(rc, 0)
        self.assertEqual((self.libgcc / "specs").read_text(), first)

    def test_dry_run_changes_nothing(self):
        rc, _, stderr = self.run_setup(dry_run=True)
        self.assertEqual(rc, 0)
        self.assertIn(f"würde schreiben: {self.libgcc / 'specs'}", stderr)
        self.assertFalse((self.libgcc / "specs").exists())
        self.assertFalse((self.libgcc / "crt1.o").exists())

    def test_clang_config_written_when_clang_exists(self):
        clang = self.prefix / "opt/llvm/bin/clang"
        clang.parent.mkdir(parents=True)
        clang.write_text("")
        rc, stdout, _ = self.run_setup()
        self.assertEqual(rc, 0, stdout)
        for name in toolchain.CLANG_CONFIGS:
            lines = (self.prefix / "etc/clang" / name).read_text().splitlines()
            self.assertEqual(lines[0], toolchain.MARKER)
            self.assertIn(f"--gcc-install-dir={self.opt_libgcc}", lines)

    def test_foreign_clang_config_is_not_overwritten(self):
        clang = self.prefix / "opt/llvm/bin/clang"
        clang.parent.mkdir(parents=True)
        clang.write_text("")
        cfg = self.prefix / "etc/clang/clang.cfg"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("# mine\n-O2\n")
        with self.assertRaises(Fehler) as ctx:
            self.run_setup()
        self.assertIn(str(cfg), str(ctx.exception))
        self.assertEqual(cfg.read_text(), "# mine\n-O2\n")
        self.assertFalse((self.libgcc / "specs").exists())

    def test_errors_without_gcc_or_sysroot(self):
        with self.assertRaises(Fehler) as ctx:
            out, _, _ = make_output()
            toolchain.setup(self.root / "none", self.runner(), out, False, self.crt, {})
        self.assertEqual(str(ctx.exception), "gcc fehlt: brew install --skip-post-install gcc")
        import shutil

        shutil.rmtree(self.prefix / "opt/steamos-sysroot")
        with self.assertRaises(Fehler) as ctx:
            self.run_setup()
        self.assertEqual(
            str(ctx.exception), "steamos-sysroot fehlt: brew install weegee/p94/steamos-sysroot"
        )


class UpgradeTest(Tree):
    def outdated(self, names):
        runner = self.runner()
        payload = {"formulae": [{"name": n} for n in names], "casks": []}
        runner.add(
            (BREW, "outdated", "--formula", "--json=v2"), Result([], 0, json.dumps(payload), "")
        )
        runner.add((BREW, "list", "--versions", "gcc"), Result([], 0, "gcc 16.2.0\n", ""))
        return runner

    def run_upgrade(self, runner, dry_run=False):
        out, stdout, stderr = make_output()
        with self.brew_env():
            rc = toolchain.gcc_upgrade(self.prefix, runner, out, dry_run, self.crt, local_db())
        return rc, stdout, stderr

    def test_up_to_date(self):
        runner = self.outdated(["wget"])
        rc, _, stderr = self.run_upgrade(runner)
        self.assertEqual(rc, 0)
        self.assertIn("gcc ist aktuell (16.2.0)", stderr.getvalue())
        self.assertNotIn([BREW, "unpin", "gcc"], runner.calls)

    def test_upgrade_steps_and_final_pin(self):
        runner = self.outdated(["gcc"])
        rc, _, _ = self.run_upgrade(runner)
        self.assertEqual(rc, 0)
        calls = [c for c in runner.calls if c[0] == BREW and c[1] in ("unpin", "install", "pin")]
        self.assertEqual(
            calls,
            [
                [BREW, "unpin", "gcc"],
                [BREW, "install", "--skip-post-install", "gcc"],
                [BREW, "pin", "gcc"],
            ],
        )
        self.assertTrue((self.libgcc / "specs").is_file())

    def test_pin_is_restored_after_failure(self):
        runner = self.outdated(["gcc"])
        runner.add((BREW, "install"), Result([], 1, "", "kaputt"))
        with self.assertRaises(Fehler):
            self.run_upgrade(runner)
        self.assertEqual(runner.calls[-1], [BREW, "pin", "gcc"])

    def test_dry_run_lists_steps_and_changes_nothing(self):
        runner = FakeRunner(dry_run=True, output=make_output()[0])
        for prefix, result in self.outdated(["gcc"])._rules:
            runner.add(prefix, result)
        rc, _, _ = self.run_upgrade(runner, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertFalse((self.libgcc / "specs").exists())


if __name__ == "__main__":
    unittest.main()

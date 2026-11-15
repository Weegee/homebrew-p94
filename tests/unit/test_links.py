import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p94brew import links as lk
from p94brew.cli import Fehler, Output
from p94brew.runner import FakeRunner, Result

UNIT_TEXT = "[Unit]\nDescription=hello\n"
LIST_TEXT = """\
# Linkliste für brew p94-link (Formel p94-hello)
format 1
unit    lib/systemd/user/p94-hello.service  enable
config  share/p94-hello/hello.conf          p94-hello/hello.conf
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ParserTest(unittest.TestCase):
    def parse(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            return lk.parse_link_list(write(Path(tmp) / "x.links", text), "x")

    def assertError(self, text: str, line: int, fragment: str):
        with self.assertRaises(lk.LinkListError) as ctx:
            self.parse(text)
        message = str(ctx.exception)
        self.assertIn(f".links:{line}:", message)
        self.assertIn(fragment, message)

    def test_valid(self):
        entries = self.parse(LIST_TEXT)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].type, "unit")
        self.assertEqual(entries[0].target_rel, "p94-hello.service")
        self.assertEqual(entries[0].options, ("enable",))
        self.assertEqual(entries[1].target_rel, "p94-hello/hello.conf")
        self.assertEqual(entries[1].line, 4)

    def test_missing_format(self):
        self.assertError("unit a.service\n", 1, "format 1")

    def test_unknown_type(self):
        self.assertError("format 1\n\nbogus a b\n", 3, "unbekannter Typ")

    def test_absolute_target(self):
        self.assertError("format 1\nconfig a /etc/x\n", 2, "absolut")

    def test_dotdot(self):
        self.assertError("format 1\nconfig a ../x\n", 2, "..")

    def test_hidden_target(self):
        self.assertError("format 1\nconfig a .x\n", 2, "'.'")

    def test_config_needs_target(self):
        self.assertError("format 1\nconfig share/a\n", 2, "ZIEL fehlt")

    def test_unknown_option(self):
        self.assertError("format 1\nunit a.service one two\n", 2, "unbekannte Option")

    def test_enable_only_for_units(self):
        self.assertError("format 1\nskill share/skill enable\n", 2, "nicht erlaubt")

    def test_default_target_is_basename(self):
        entries = self.parse("format 1\nskill share/skills/hello\n")
        self.assertEqual(entries[0].target_rel, "hello")


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name).resolve()
        self.prefix = root / "prefix"
        self.home = root / "home"
        self.config = self.home / ".config"
        self.data = self.home / ".local/share"
        self.state_path = self.home / ".local/state/p94-link/state.json"
        self.home.mkdir()
        self.add_formula(
            "p94-hello",
            LIST_TEXT,
            {
                "lib/systemd/user/p94-hello.service": UNIT_TEXT,
                "share/p94-hello/hello.conf": "x=1\n",
            },
        )

    def add_formula(self, name: str, list_text: str, files: dict[str, str]):
        keg = self.prefix / "Cellar" / name / "1.0"
        for rel, text in files.items():
            write(keg / rel, text)
        write(keg / "share/p94-links" / f"{name}.links", list_text)
        (self.prefix / "opt").mkdir(parents=True, exist_ok=True)
        opt = self.prefix / "opt" / name
        if not opt.is_symlink():
            opt.symlink_to(f"../Cellar/{name}/1.0")
        links_dir = self.prefix / "share/p94-links"
        links_dir.mkdir(parents=True, exist_ok=True)
        link = links_dir / f"{name}.links"
        if not link.is_symlink():
            link.symlink_to(f"../../opt/{name}/share/p94-links/{name}.links")

    def remove_formula(self, name: str):
        (self.prefix / "opt" / name).unlink()
        (self.prefix / "share/p94-links" / f"{name}.links").unlink()

    def run_link(self, *, remove=False, selected=None, dry=False, fake=None):
        out, err = io.StringIO(), io.StringIO()
        output = Output("t", env={"LANG": "C"}, out=out, err=err)
        sel = set(selected) if selected else None
        links, protected, failures = lk._collect(
            self.prefix, sel, self.home, self.config, self.data, output
        )
        state = lk.load_state(self.state_path)
        plan = lk.make_plan(links, state, sel, remove, prefix=self.prefix, protected=protected)
        runner = fake or FakeRunner(dry_run=dry, output=output)
        code = lk.apply_plan(
            plan,
            state,
            runner,
            output,
            dry,
            state_path=self.state_path,
            home=self.home,
            config_home=self.config,
            data_home=self.data,
            prefix=self.prefix,
        )
        self.out, self.err, self.plan, self.runner = out.getvalue(), err.getvalue(), plan, runner
        return 1 if failures else code

    @property
    def unit_target(self) -> Path:
        return self.config / "systemd/user/p94-hello.service"

    @property
    def conf_target(self) -> Path:
        return self.config / "p94-hello/hello.conf"

    def changing_calls(self, runner=None):
        runner = runner or self.runner
        return [c for c in runner.calls if c[2] != "is-enabled"]

    def enabled_runner(self):
        fake = FakeRunner()
        fake.add(("systemctl", "--user", "is-enabled"), Result([], 0, "enabled\n", ""))
        return fake


class ResolveTest(Fixture):
    def test_missing_source(self):
        (self.prefix / "Cellar/p94-hello/1.0/share/p94-hello/hello.conf").unlink()
        output = Output("t", env={}, out=io.StringIO(), err=io.StringIO())
        links, protected, failures = lk._collect(
            self.prefix, None, self.home, self.config, self.data, output
        )
        self.assertEqual((links, failures), ([], 1))
        self.assertEqual(protected, {"p94-hello"})

    def test_source_outside_keg(self):
        keg = self.prefix / "Cellar/p94-hello/1.0"
        outside = write(Path(self._tmp.name) / "outside.conf", "evil\n")
        (keg / "share/p94-hello/hello.conf").unlink()
        (keg / "share/p94-hello/hello.conf").symlink_to(outside)
        entries = lk.parse_link_list(keg / "share/p94-links/p94-hello.links", "p94-hello")
        with self.assertRaises(lk.LinkListError) as ctx:
            lk.resolve(entries, self.prefix, self.home, self.config, self.data)
        self.assertIn("außerhalb", str(ctx.exception))


class ApplyTest(Fixture):
    def test_first_run(self):
        self.assertEqual(self.run_link(), 0)
        self.assertEqual(
            os.readlink(self.unit_target),
            str(self.prefix / "opt/p94-hello/lib/systemd/user/p94-hello.service"),
        )
        self.assertEqual(
            os.readlink(self.conf_target),
            str(self.prefix / "opt/p94-hello/share/p94-hello/hello.conf"),
        )
        state = lk.load_state(self.state_path)
        self.assertEqual(len(state), 2)
        self.assertEqual(self.runner.calls.count(["systemctl", "--user", "daemon-reload"]), 1)
        self.assertIn(["systemctl", "--user", "enable", "p94-hello.service"], self.runner.calls)
        self.assertIn("verlinkt", self.out)
        self.assertIn("2 Links angelegt", self.err)

    def test_second_run_changes_nothing(self):
        self.run_link()
        fake = self.enabled_runner()
        self.assertEqual(self.run_link(fake=fake), 0)
        self.assertEqual(self.changing_calls(fake), [])
        self.assertEqual(self.out, "")
        self.assertIn("aktuell", self.err)

    def test_changed_unit_content_reloads(self):
        self.run_link()
        write(
            self.prefix / "Cellar/p94-hello/1.0/lib/systemd/user/p94-hello.service",
            UNIT_TEXT + "X=1\n",
        )
        fake = self.enabled_runner()
        self.run_link(fake=fake)
        self.assertEqual(self.changing_calls(fake), [["systemctl", "--user", "daemon-reload"]])
        self.assertEqual(self.out, "")

    def test_line_removed_from_list(self):
        self.run_link()
        keg_list = self.prefix / "Cellar/p94-hello/1.0/share/p94-links/p94-hello.links"
        write(keg_list, "format 1\nconfig share/p94-hello/hello.conf p94-hello/hello.conf\n")
        fake = self.enabled_runner()
        self.run_link(fake=fake)
        self.assertFalse(os.path.lexists(self.unit_target))
        calls = fake.calls
        self.assertLess(
            calls.index(["systemctl", "--user", "disable", "--now", "p94-hello.service"]),
            calls.index(["systemctl", "--user", "daemon-reload"]),
        )
        self.assertTrue(os.path.islink(self.conf_target))
        self.assertEqual(len(lk.load_state(self.state_path)), 1)

    def test_unit_not_loaded_does_not_stop_the_removal(self):
        self.run_link()
        self.remove_formula("p94-hello")
        fake = self.enabled_runner()
        fake.add(
            ("systemctl", "--user", "disable"),
            Result(
                [], 5, "", "Failed to stop p94-hello.service: Unit p94-hello.service not loaded.\n"
            ),
        )
        self.assertEqual(self.run_link(fake=fake), 0)
        self.assertFalse(os.path.lexists(self.unit_target))
        self.assertIn(["systemctl", "--user", "daemon-reload"], fake.calls)

    def test_other_disable_errors_still_fail(self):
        self.run_link()
        self.remove_formula("p94-hello")
        fake = self.enabled_runner()
        fake.add(("systemctl", "--user", "disable"), Result([], 1, "", "Access denied\n"))
        with self.assertRaises(Fehler) as ctx:
            self.run_link(fake=fake)
        self.assertIn("endete mit 1: Access denied", str(ctx.exception))
        self.assertTrue(os.path.lexists(self.unit_target))

    def test_formula_gone(self):
        self.run_link()
        self.remove_formula("p94-hello")
        self.run_link(fake=self.enabled_runner())
        self.assertFalse(os.path.lexists(self.unit_target))
        self.assertFalse(os.path.lexists(self.conf_target))
        self.assertFalse((self.config / "p94-hello").exists())
        self.assertTrue(self.config.is_dir())
        self.assertEqual(lk.load_state(self.state_path), [])

    def test_foreign_file_is_a_conflict(self):
        write(self.conf_target, "mine\n")
        self.assertEqual(self.run_link(), 1)
        self.assertEqual(self.conf_target.read_text(), "mine\n")
        self.assertIn("Konflikt", self.out)
        self.assertTrue(os.path.islink(self.unit_target))
        targets = [e["target"] for e in lk.load_state(self.state_path)]
        self.assertNotIn(str(self.conf_target), targets)

    def test_foreign_symlink_is_a_conflict(self):
        self.conf_target.parent.mkdir(parents=True)
        self.conf_target.symlink_to("/etc/hostname")
        self.assertEqual(self.run_link(), 1)
        self.assertEqual(os.readlink(self.conf_target), "/etc/hostname")

    def test_old_version_link_is_replaced(self):
        self.conf_target.parent.mkdir(parents=True)
        self.conf_target.symlink_to(self.prefix / "Cellar/p94-hello/0.9/share/p94-hello/hello.conf")
        self.assertEqual(self.run_link(), 0)
        self.assertEqual(
            os.readlink(self.conf_target),
            str(self.prefix / "opt/p94-hello/share/p94-hello/hello.conf"),
        )

    def test_remove_selected_only(self):
        self.add_formula(
            "p94-other", "format 1\ndata share/o.txt other/o.txt\n", {"share/o.txt": "o\n"}
        )
        self.run_link()
        other = self.data / "other/o.txt"
        self.assertTrue(os.path.islink(other))
        self.run_link(remove=True, selected=["p94-hello"], fake=self.enabled_runner())
        self.assertFalse(os.path.lexists(self.unit_target))
        self.assertFalse(os.path.lexists(self.conf_target))
        self.assertTrue(os.path.islink(other))
        self.assertEqual([e["formula"] for e in lk.load_state(self.state_path)], ["p94-other"])

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_link(dry=True), 0)
        self.assertFalse(os.path.lexists(self.unit_target))
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.changing_calls(), [])
        self.assertIn("würde verlinken", self.out)

    def test_dry_run_remove_keeps_links(self):
        self.run_link()
        self.run_link(remove=True, dry=True, fake=FakeRunner(dry_run=True))
        self.assertTrue(os.path.islink(self.unit_target))
        self.assertIn("würde entfernen", self.out)
        self.assertEqual(len(lk.load_state(self.state_path)), 2)

    def wants_link(self, version: str = "1.0") -> Path:
        """A link as systemctl enable writes it: resolved through opt/ into the keg."""
        wants = self.config / "systemd/user/default.target.wants/p94-hello.service"
        wants.parent.mkdir(parents=True, exist_ok=True)
        wants.symlink_to(
            self.prefix / f"Cellar/p94-hello/{version}/lib/systemd/user/p94-hello.service"
        )
        return wants

    def test_wants_link_into_keg_points_at_unit_link(self):
        self.run_link()
        wants = self.wants_link()
        self.assertEqual(self.run_link(fake=self.enabled_runner()), 0)
        self.assertEqual(os.readlink(wants), str(self.unit_target))
        self.assertIn("umgebogen", self.out)
        self.assertIn("1 Aktivierungslink umgebogen", self.err)
        self.assertEqual(self.changing_calls(), [])

    def test_dangling_wants_link_after_upgrade_is_repaired(self):
        self.run_link()
        wants = self.wants_link()
        keg = self.prefix / "Cellar/p94-hello"
        (keg / "1.0").rename(keg / "2.0")
        opt = self.prefix / "opt/p94-hello"
        opt.unlink()
        opt.symlink_to("../Cellar/p94-hello/2.0")
        self.assertFalse(wants.exists())
        self.assertEqual(self.run_link(fake=self.enabled_runner()), 0)
        self.assertTrue(wants.exists())
        self.assertEqual(os.readlink(wants), str(self.unit_target))

    def test_wants_link_dry_run_keeps_link(self):
        self.run_link()
        wants = self.wants_link()
        self.run_link(dry=True, fake=FakeRunner(dry_run=True))
        self.assertIn("/Cellar/p94-hello/1.0/", os.readlink(wants))
        self.assertIn("würde umbiegen", self.out)
        self.assertIn("1 Aktivierungslink würde umgebogen", self.err)

    def test_wants_link_of_unit_without_enable_option(self):
        list_path = self.prefix / "Cellar/p94-hello/1.0/share/p94-links/p94-hello.links"
        write(list_path, LIST_TEXT.replace("  enable\n", "\n"))
        self.run_link()
        wants = self.wants_link()
        self.run_link(fake=self.enabled_runner())
        self.assertEqual(os.readlink(wants), str(self.unit_target))

    def test_foreign_wants_link_is_left_alone(self):
        self.run_link()
        wants = self.config / "systemd/user/default.target.wants/p94-hello.service"
        wants.parent.mkdir(parents=True, exist_ok=True)
        wants.symlink_to("/usr/lib/systemd/user/p94-hello.service")
        self.run_link(fake=self.enabled_runner())
        self.assertEqual(os.readlink(wants), "/usr/lib/systemd/user/p94-hello.service")
        self.assertNotIn("umgebogen", self.out)

    def test_broken_list_keeps_existing_links(self):
        self.run_link()
        keg_list = self.prefix / "Cellar/p94-hello/1.0/share/p94-links/p94-hello.links"
        write(keg_list, "format 2\n")
        self.assertEqual(self.run_link(fake=self.enabled_runner()), 1)
        self.assertTrue(os.path.islink(self.unit_target))
        self.assertEqual(len(lk.load_state(self.state_path)), 2)


class MainTest(Fixture):
    def call_main(self, *argv):
        env_vars = {
            "HOME": str(self.home),
            "P94_BREW_PREFIX": str(self.prefix),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_RUNTIME_DIR": str(self.home),
            "TERM": "dumb",
        }
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, env_vars),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = lk.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_list_prints_table(self):
        self.run_link()
        code, out, _ = self.call_main("--list")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("FORMEL"))
        self.assertIn("~/.config/systemd/user/p94-hello.service", out)
        self.assertIn("~/.config/p94-hello/hello.conf", out)

    def test_no_lists(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        self.prefix = empty
        code, _, err = self.call_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("keine Linklisten gefunden", err)

    def test_dry_run_via_main(self):
        code, out, _ = self.call_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("würde verlinken", out)
        self.assertFalse(os.path.lexists(self.unit_target))


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import unittest
from unittest import mock

from p94brew import cli


class Tty(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


UTF8 = {"LANG": "de_DE.UTF-8"}


class UseColorTest(unittest.TestCase):
    def test_choice_always_beats_no_color(self):
        self.assertTrue(cli.use_color(Tty(False), "always", {"NO_COLOR": "1"}))

    def test_choice_never_beats_force_color(self):
        self.assertFalse(cli.use_color(Tty(True), "never", {"FORCE_COLOR": "1"}))

    def test_no_color_beats_force_color(self):
        self.assertFalse(cli.use_color(Tty(True), "auto", {"NO_COLOR": "1", "FORCE_COLOR": "1"}))

    def test_homebrew_no_color(self):
        self.assertFalse(cli.use_color(Tty(True), "auto", {"HOMEBREW_NO_COLOR": "1", "TERM": "x"}))

    def test_force_color_without_tty(self):
        self.assertTrue(cli.use_color(Tty(False), "auto", {"FORCE_COLOR": "1", "TERM": "dumb"}))

    def test_force_color_zero_is_ignored(self):
        self.assertFalse(cli.use_color(Tty(False), "auto", {"FORCE_COLOR": "0", "TERM": "xterm"}))

    def test_dumb_terminal(self):
        self.assertFalse(cli.use_color(Tty(True), "auto", {"TERM": "dumb"}))

    def test_missing_term(self):
        self.assertFalse(cli.use_color(Tty(True), "auto", {}))

    def test_terminal(self):
        self.assertTrue(cli.use_color(Tty(True), "auto", {"TERM": "xterm-256color"}))

    def test_pipe(self):
        self.assertFalse(cli.use_color(Tty(False), "auto", {"TERM": "xterm-256color"}))


class Utf8Test(unittest.TestCase):
    def test_utf8(self):
        self.assertTrue(cli.utf8_ok({"LANG": "de_DE.UTF-8"}))

    def test_c_locale(self):
        self.assertFalse(cli.utf8_ok({"LANG": "C"}))

    def test_homebrew_copy(self):
        self.assertTrue(cli.utf8_ok({"HOMEBREW_LC_ALL": "C.UTF-8"}))

    def test_first_set_wins(self):
        self.assertFalse(cli.utf8_ok({"LC_ALL": "C", "LANG": "de_DE.UTF-8"}))

    def test_nothing_set(self):
        self.assertFalse(cli.utf8_ok({}))


class OutputTest(unittest.TestCase):
    def make(self, env=None, **kw):
        out, err = Tty(False), Tty(False)
        return cli.Output("p94-test", env=env or UTF8, out=out, err=err, **kw), out, err

    def test_error_plain(self):
        o, out, err = self.make()
        o.error("kaputt")
        self.assertEqual(err.getvalue(), "p94-test: Fehler: kaputt\n")
        self.assertEqual(out.getvalue(), "")

    def test_error_colored(self):
        o, _, err = self.make(color="always")
        o.error("kaputt")
        self.assertIn("\033[31mFehler:\033[0m", err.getvalue())

    def test_warn(self):
        o, _, err = self.make()
        o.warn("vorsicht")
        self.assertEqual(err.getvalue(), "p94-test: Warnung: vorsicht\n")

    def test_check_utf8(self):
        o, out, _ = self.make()
        o.check(True, "a")
        self.assertTrue(out.getvalue().startswith("✓ a"))

    def test_check_ascii(self):
        o, out, _ = self.make(env={"LANG": "C"})
        o.check(True, "a")
        o.check(False, "b", "Abhilfe")
        o.check(None, "c")
        self.assertEqual(out.getvalue(), "OK a\nFEHLER b\n  Abhilfe\nWARNUNG c\n")

    def test_quiet_hides_notes(self):
        o, _, err = self.make(quiet=True)
        o.note("x")
        o.info("y")
        o.error("z")
        self.assertEqual(err.getvalue(), "p94-test: Fehler: z\n")

    def test_detail_needs_verbose(self):
        o, _, err = self.make()
        o.detail("a")
        self.assertEqual(err.getvalue(), "")
        o2, _, err2 = self.make(verbose=1)
        o2.detail("a")
        self.assertEqual(err2.getvalue(), "a\n")

    def test_table(self):
        o, out, _ = self.make()
        o.table(["A", "BB"], [["xxx", "1"], ["y", "22"]])
        self.assertEqual(out.getvalue(), "A    BB\nxxx  1\ny    22\n")


class HelpWidthTest(unittest.TestCase):
    def render(self, columns):
        parser = cli.make_parser(
            "prog",
            "Eine lange Beschreibung, die weit über die Breite hinausgeht und umbrochen wird.",
            epilog="Beispiele:\n  prog --eine-sehr-lange-option WERT --noch-eine-option WERT2 ENDE",
        )
        with mock.patch.dict("os.environ", {"COLUMNS": str(columns)}):
            return parser.format_help()

    def test_wraps_description_and_epilog_at_columns(self):
        text = self.render(40)
        self.assertLessEqual(max(len(line) for line in text.splitlines()), 40)
        self.assertIn("Beispiele:\n  prog --eine-sehr-lange-option", text)

    def test_keeps_short_lines(self):
        text = self.render(200)
        self.assertIn(
            "Beispiele:\n  prog --eine-sehr-lange-option WERT --noch-eine-option WERT2 ENDE", text
        )


class MiscTest(unittest.TestCase):
    def test_plural(self):
        self.assertEqual(cli.plural(1, "Formel", "Formeln"), "1 Formel")
        self.assertEqual(cli.plural(3, "Formel", "Formeln"), "3 Formeln")
        self.assertEqual(cli.plural(0, "Formel", "Formeln"), "0 Formeln")

    def test_parser_unknown_option(self):
        parser = cli.make_parser("p94-test", "Test")
        cli.add_common_options(parser, "1")
        err = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(err):
                parser.parse_args(["--nope"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("p94-test: Fehler: unbekannte Option: --nope", err.getvalue())
        self.assertIn("Hilfe: p94-test --help", err.getvalue())

    def test_parser_invalid_choice(self):
        parser = cli.make_parser("p94-test", "Test")
        parser.add_argument("command", choices=("check", "setup"), metavar="check|setup")
        err = io.StringIO()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(err):
                parser.parse_args(["bogus"])
        self.assertIn(
            "p94-test: Fehler: ungültiger Wert 'bogus' für check|setup; erlaubt: check, setup",
            err.getvalue(),
        )

    def test_parser_usage_prefix(self):
        parser = cli.make_parser("p94-test", "Test")
        self.assertTrue(parser.format_usage().startswith("Aufruf: "))

    def test_parser_accepts_common_options(self):
        parser = cli.make_parser("p94-test", "Test")
        cli.add_common_options(parser, "1")
        args = parser.parse_args(["-q", "-vv", "--color", "never"])
        self.assertTrue(args.quiet)
        self.assertEqual(args.verbose, 2)
        self.assertEqual(args.color, "never")


if __name__ == "__main__":
    unittest.main()

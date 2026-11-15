import io
import unittest

from p94brew.cli import Fehler, Output
from p94brew.runner import FakeRunner, Result, Runner


class RunnerTest(unittest.TestCase):
    def test_run_captures(self):
        res = Runner().run(["/bin/echo", "hallo"])
        self.assertEqual(res.stdout, "hallo\n")
        self.assertEqual(res.returncode, 0)

    def test_check_raises(self):
        with self.assertRaises(Fehler):
            Runner().run(["/bin/false"], check=True)

    def test_change_dry_run_calls_nothing(self):
        err = io.StringIO()
        out = Output("t", err=err, env={})
        res = Runner(dry_run=True, output=out).change(["/bin/false"], check=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("würde ausführen: /bin/false", err.getvalue())

    def test_captured_command_does_not_wait_for_stdin(self):
        res = Runner().run(["/bin/cat"])  # would hang on an inherited terminal or pipe
        self.assertEqual((res.returncode, res.stdout), (0, ""))

    def test_env_extra(self):
        res = Runner(env={"A": "1"}).run(["/bin/sh", "-c", "echo $A$B"], env_extra={"B": "2"})
        self.assertEqual(res.stdout, "12\n")


class FakeRunnerTest(unittest.TestCase):
    def test_later_rule_overrides_an_equal_prefix(self):
        fake = FakeRunner()
        fake.add(("x",), Result([], 0, "first", ""))
        fake.add(("x",), Result([], 0, "second", ""))
        self.assertEqual(fake.run(["x"]).stdout, "second")

    def test_longest_prefix_wins(self):
        fake = FakeRunner()
        fake.add(("brew",), Result([], 1, "", "kurz"))
        fake.add(("brew", "list"), Result([], 0, "lang", ""))
        self.assertEqual(fake.run(["brew", "list", "x"]).stdout, "lang")
        self.assertEqual(fake.run(["brew", "info"]).returncode, 1)
        self.assertEqual(fake.calls, [["brew", "list", "x"], ["brew", "info"]])

    def test_default_result(self):
        self.assertEqual(FakeRunner().run(["x"]).returncode, 0)

    def test_check_raises(self):
        fake = FakeRunner()
        fake.add(("x",), Result([], 3, "", "boom"))
        with self.assertRaises(Fehler):
            fake.run(["x"], check=True)


if __name__ == "__main__":
    unittest.main()

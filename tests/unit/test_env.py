import unittest
from pathlib import Path

from p94brew import env


class RestoreTest(unittest.TestCase):
    def test_takes_homebrew_copy(self):
        e = {"HOMEBREW_XDG_RUNTIME_DIR": "/tmp/run", "HOMEBREW_LANG": "de_DE.UTF-8"}
        env.restore_user_env(e)
        self.assertEqual(e["XDG_RUNTIME_DIR"], "/tmp/run")
        self.assertEqual(e["LANG"], "de_DE.UTF-8")

    def test_does_not_override(self):
        e = {"XDG_RUNTIME_DIR": "/tmp/mine", "HOMEBREW_XDG_RUNTIME_DIR": "/tmp/run"}
        env.restore_user_env(e)
        self.assertEqual(e["XDG_RUNTIME_DIR"], "/tmp/mine")


class PrefixTest(unittest.TestCase):
    def test_default(self):
        self.assertEqual(env.brew_prefix({}), env.DEFAULT_PREFIX)

    def test_homebrew_prefix(self):
        self.assertEqual(env.brew_prefix({"HOMEBREW_PREFIX": "/a"}), Path("/a"))

    def test_test_hook_wins(self):
        e = {"HOMEBREW_PREFIX": "/a", "P94_BREW_PREFIX": "/b"}
        self.assertEqual(env.brew_prefix(e), Path("/b"))

    def test_brew_bin(self):
        self.assertEqual(env.brew_bin({"HOMEBREW_PREFIX": "/a"}), Path("/a/bin/brew"))
        self.assertEqual(env.brew_bin({"HOMEBREW_BREW_FILE": "/x/brew"}), Path("/x/brew"))


class XdgTest(unittest.TestCase):
    def test_fallbacks(self):
        e = {"HOME": "/h"}
        self.assertEqual(env.xdg_state_home(e), Path("/h/.local/state"))
        self.assertEqual(env.xdg_cache_home(e), Path("/h/.cache"))
        self.assertEqual(env.xdg_config_home(e), Path("/h/.config"))
        self.assertEqual(env.xdg_data_home(e), Path("/h/.local/share"))

    def test_variable_wins(self):
        self.assertEqual(env.xdg_cache_home({"HOME": "/h", "XDG_CACHE_HOME": "/c"}), Path("/c"))

    def test_runtime_dir(self):
        self.assertEqual(env.runtime_dir({"XDG_RUNTIME_DIR": "/r"}), Path("/r"))


if __name__ == "__main__":
    unittest.main()

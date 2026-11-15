"""Tests of p94-brew-migrate in a throw-away environment (HOME, prefix, chezmoi source)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p94brew import migrate
from p94brew.cli import Fehler
from p94brew.runner import FakeRunner, Result

from .test_gitsrc import GIT_ENV, commit_file, git, make_repo

GRAFT_VERSION = "0.25.0"
VERSIONS = {
    "gh": "gh version 2.103.3 (2026-10-26)\n",
    "node": "v24.22.1\n",
    "nvim": "NVIM v0.12.6\n",
    "diff-so-fancy": "",
    "chezmoi": "chezmoi version v2.73.3, commit abc\n",
    "ethtool": "ethtool version 7.1\n",
}
FORMULAE = {
    "gh": "gh",
    "node@24": "node@24",
    "neovim": "neovim",
    "diff-so-fancy": "diff-so-fancy",
    "chezmoi": "chezmoi",
    "weegee/p94/steamos-tools": "steamos-tools",
}


def touch_exe(path: Path, text: str = "#!/bin/sh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def template_files() -> dict[str, str]:
    settings = ["{{- /* Kopf */ -}}"] * 8 + [migrate.GRAFT_OLD] + ["x"] * 2 + [migrate.BRAIN_OLD]
    ignore = ["# Datei"] * 66 + [migrate.IGNORE_OLD, "{{- end }}"]
    gitconfig = [
        migrate.GH_COMMENT_OLD,
        '{{- $gh := "/usr/bin/gh" -}}',
        migrate.GH_BLOCK_OLD,
        "{{- end -}}",
        "[user]",
    ]
    return {
        "dot_claude/settings.json.tmpl": "\n".join(settings) + "\nrest graft-hooks\n",
        ".chezmoiignore": "\n".join(ignore) + "\n",
        "dot_config/git/config.tmpl": "\n".join(gitconfig) + "\n",
    }


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.prefix = self.root / "brew"
        self.state = self.home / ".local/state"
        self.bin = self.home / ".local/bin"
        self.make_old_tools()
        touch_exe(self.prefix / "bin/brew")
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude/settings.json").write_text('{"hooks": "graft-hooks"}\n')
        (self.home / ".config/git").mkdir(parents=True)
        (self.home / ".config/git/config").write_text(
            f"[credential]\n\thelper = {self.prefix}/bin/gh\n"
        )
        self.repo = make_repo(self.root / "chezmoi")
        for rel, text in template_files().items():
            commit_file(self.repo, f"home/{rel}", text)
        self.src = self.repo / "home"
        patcher = mock.patch.dict(
            os.environ,
            {
                **GIT_ENV,
                "HOME": str(self.home),
                "P94_BREW_PREFIX": str(self.prefix),
                "XDG_STATE_HOME": str(self.state),
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        restore = mock.patch.object(migrate.env, "restore_user_env")
        restore.start()
        self.addCleanup(restore.stop)
        self.runner = self.new_runner()

    # -- old installation -------------------------------------------------------------------
    def make_old_tools(self):
        opt = self.home / ".local/opt"
        self.bin.mkdir(parents=True)

        def link(name: str, target: str):
            (self.bin / name).symlink_to(target)

        touch_exe(opt / "gh_2.103.3_linux_amd64/bin/gh")
        link("gh", "../opt/gh_2.103.3_linux_amd64/bin/gh")
        for tool in ("node", "npm", "npx", "corepack"):
            touch_exe(opt / f"node-v24.22.1-linux-x64/bin/{tool}")
            link(tool, f"../opt/node-v24.22.1-linux-x64/bin/{tool}")
        graft = self.home / ".local/lib/node_modules/@nanonets/graft"
        touch_exe(graft / "dist/bin/graft.js")
        (graft / "package.json").write_text(json.dumps({"version": GRAFT_VERSION}))
        link("graft", "../lib/node_modules/@nanonets/graft/dist/bin/graft.js")
        touch_exe(opt / "nvim-v0.12.6-linux-x86_64/bin/nvim")
        link("nvim", "../opt/nvim-v0.12.6-linux-x86_64/bin/nvim")
        touch_exe(opt / "diff-so-fancy-v1.4.14/diff-so-fancy")
        link("diff-so-fancy", "../opt/diff-so-fancy-v1.4.14/diff-so-fancy")
        touch_exe(self.bin / "chezmoi")
        for tool in ("ethtool", "turbostat", "vainfo"):
            touch_exe(opt / f"sysinfo-tools-3.9/bin/{tool}")
            link(tool, str(opt / f"sysinfo-tools-3.9/bin/{tool}"))
        touch_exe(self.bin / "steam-chat-lite")  # an excluded tool: must stay

    # -- fake commands ----------------------------------------------------------------------
    def new_runner(self, installed=False):
        runner = FakeRunner(passthrough=("git",))
        brew = str(self.prefix / "bin/brew")
        for formula in FORMULAE:
            info = {
                "formulae": [{"versions": {"stable": "1.0"}, "installed": [1] if installed else []}]
            }
            runner.add((brew, "info", "--json=v2", formula), Result([], 0, json.dumps(info), ""))
        cask = {"casks": [{"version": "2.1", "installed": None}]}
        runner.add(
            (brew, "info", "--json=v2", "--cask", "claude-code@latest"),
            Result([], 0, json.dumps(cask), ""),
        )
        for command, text in VERSIONS.items():
            runner.add((str(self.bin / command), "--version"), Result([], 0, text, ""))
        runner.add(
            (str(self.prefix / "bin/graft"), "--version"),
            Result([], 0, f"graft {GRAFT_VERSION}\n", ""),
        )
        for tool in migrate.TOOLS:
            for command in tool.commands:
                runner.add(
                    ("bash", "-lic", f"command -v {command}"),
                    Result([], 0, f"{self.prefix}/bin/{command}\n", ""),
                )
        runner.add((str(self.prefix / "bin/gh"), "auth", "status"), Result([], 0, "", ""))
        return runner

    def run_main(self, *argv, runner=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = migrate.main(
                [*argv, "--chezmoi-source", str(self.src), "--color", "never"],
                runner or self.runner,
            )
        return rc, out.getvalue(), err.getvalue()

    def snapshot(self, root: Path):
        entries = []
        for path in sorted(root.rglob("*")):
            target = os.readlink(path) if path.is_symlink() else ""
            entries.append(
                (str(path.relative_to(root)), target, path.stat().st_size if path.is_file() else -1)
            )
        return entries

    def backups(self):
        return sorted((self.state / "homebrew-umstieg").glob("backup-*"))

    def calls(self, *prefix):
        return [c for c in self.runner.calls if tuple(c[: len(prefix)]) == prefix]


class DryRunTest(Fixture):
    def test_dry_run_changes_nothing(self):
        before = (self.snapshot(self.home), self.snapshot(self.repo))
        rc, out, _ = self.run_main("--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual((self.snapshot(self.home), self.snapshot(self.repo)), before)
        rows = [
            line
            for line in out.splitlines()
            if line.split()[:1] and line.split()[0] in {t.key for t in migrate.TOOLS}
        ]
        self.assertEqual(
            [r.split()[0] for r in rows],
            ["gh", "node", "neovim", "diff-so-fancy", "chezmoi", "steamos-tools"],
        )
        self.assertNotIn("claude ", out.replace("claude-", ""))
        self.assertIn("Bleibt:", out)
        self.assertEqual(out.count("würde ändern:"), 4)
        self.assertIn("dot_claude/settings.json.tmpl:9", out)
        self.assertIn("~/.local/bin/gh gh version 2.103.3", out)

    def test_dry_run_with_claude_code(self):
        (self.bin / "claude").symlink_to(self.home / ".local/share/claude/versions/2.1.318")
        runner = self.new_runner()
        runner.add(
            (str(self.bin / "claude"), "--version"), Result([], 0, "2.1.318 (Claude Code)\n", "")
        )
        rc, out, _ = self.run_main("--dry-run", "--with-claude-code", runner=runner)
        self.assertEqual(rc, 0)
        self.assertIn("claude-code@latest", out)


class MigrateTest(Fixture):
    def test_real_run_moves_everything_to_the_backup(self):
        rc, _, err = self.run_main("-y")
        self.assertEqual(rc, 0, err)
        (backup,) = self.backups()
        manifest = json.loads((backup / "manifest.json").read_text())["entries"]
        self.assertEqual(len(manifest), 18)
        for entry in manifest:
            rel = Path(entry["source"]).relative_to(self.home)
            self.assertTrue(os.path.lexists(backup / rel), rel)
            self.assertFalse(os.path.lexists(entry["source"]), rel)
        self.assertTrue((backup / ".local/bin/gh").is_symlink())
        self.assertTrue((backup / ".local/opt/node-v24.22.1-linux-x64/bin/node").exists())
        self.assertTrue((backup / ".local/lib/node_modules/@nanonets/graft/package.json").exists())
        self.assertTrue((self.bin / "steam-chat-lite").exists())  # excluded tools stay
        self.assertEqual(sorted(p.name for p in self.bin.iterdir()), ["steam-chat-lite"])

    def test_templates_replaced_exactly_and_committed_once(self):
        before = git(self.repo, "rev-list", "--count", "HEAD")
        self.run_main("-y")
        self.assertEqual(int(git(self.repo, "rev-list", "--count", "HEAD")), int(before) + 1)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), migrate.TEMPLATE_COMMIT)
        settings = (self.src / "dot_claude/settings.json.tmpl").read_text().splitlines()
        self.assertEqual(settings[8], migrate.GRAFT_NEW)
        self.assertEqual(settings[11], migrate.BRAIN_NEW)
        self.assertEqual(
            (self.src / ".chezmoiignore").read_text().splitlines()[66], migrate.IGNORE_NEW
        )
        config = (self.src / "dot_config/git/config.tmpl").read_text()
        self.assertTrue(config.startswith(migrate.GH_COMMENT_NEW + "\n"))
        self.assertIn(migrate.GH_BLOCK_NEW + "\n{{- end -}}", config)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(self.calls("git", "-C", str(self.repo), "push"), [])

    def test_push_only_with_the_option(self):
        self.runner.add(("git", "-C", str(self.repo), "push"), Result([], 0, "", ""))
        self.run_main("-y", "--push")
        self.assertEqual(len(self.calls("git", "-C", str(self.repo), "push")), 1)

    def test_second_run_moves_nothing(self):
        self.run_main("-y")
        self.runner = self.new_runner(installed=True)
        rc, _, err = self.run_main("-y", runner=self.runner)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err.count("schon umgestellt"), 6)
        self.assertEqual(len(self.backups()), 1)

    def test_gh_check_fails_and_the_old_gh_stays(self):
        self.runner.add(
            (str(self.prefix / "bin/gh"), "auth", "status"),
            Result([], 1, "", "You are not logged in"),
        )
        rc, _, err = self.run_main("-y", "gh")
        self.assertEqual(rc, 1)
        self.assertTrue((self.bin / "gh").is_symlink())
        brew = str(self.prefix / "bin/brew")
        self.assertEqual(len(self.calls(brew, "uninstall", "gh")), 1)
        self.assertEqual(
            len(self.calls("chezmoi", "apply", str(self.home / ".config/git/config"))), 2
        )
        self.assertIn("Anmeldung", err)
        self.assertEqual(self.backups(), [])

    def test_gh_check_fails_when_the_helper_is_missing(self):
        (self.home / ".config/git/config").write_text("[credential]\n\thelper = /usr/bin/gh\n")
        rc, _, err = self.run_main("-y", "gh")
        self.assertEqual(rc, 1)
        self.assertIn("zeigt nicht auf", err)
        self.assertTrue((self.bin / "gh").is_symlink())

    def test_npm_retry_with_ignore_scripts(self):
        npm = str(self.prefix / "opt/node@24/bin/npm")
        spec = f"@nanonets/graft@{GRAFT_VERSION}"
        self.runner.add((npm, "install", "-g", spec), Result([], 1, "", "gyp ERR"))
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.calls(npm, "install", "-g", "--ignore-scripts", spec)), 1)
        script = str(self.prefix / "lib/node_modules/@nanonets/graft/dist/bin/graft.js")
        self.assertEqual(len(self.calls("chmod", "+x", script)), 1)
        self.assertFalse(os.path.lexists(self.bin / "node"))

    def test_npm_runs_with_homebrew_node_prefix_and_compiler(self):
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 0, err)
        npm = str(self.prefix / "opt/node@24/bin/npm")
        spec = f"@nanonets/graft@{GRAFT_VERSION}"
        index = self.runner.calls.index([npm, "install", "-g", spec, "--prefix", str(self.prefix)])
        env = self.runner.envs[index]
        self.assertTrue(env["PATH"].startswith(f"{self.prefix}/opt/node@24/bin:{self.prefix}/bin"))
        self.assertEqual(env["CXX"], os.environ.get("CXX", "c++"))
        self.assertEqual(env["CC"], os.environ.get("CC", "cc"))

    def test_settings_with_graft_hooks_are_not_applied_again(self):
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 0, err)
        settings = str(self.home / ".claude/settings.json")
        self.assertEqual(self.calls("chezmoi", "apply", settings), [])

    def test_settings_without_graft_hooks_are_applied(self):
        settings = self.home / ".claude/settings.json"
        settings.write_text("{}\n")
        self.runner.add(("chezmoi", "apply", str(settings)), Result([], 1, "", "no tty"))
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 1)
        self.assertIn("chezmoi diff ~/.claude/settings.json", err)
        self.assertTrue((self.bin / "node").is_symlink())

    def test_npmrc_with_only_the_old_prefix_moves_to_the_backup(self):
        (self.home / ".npmrc").write_text(f"prefix={self.home}/.local\n")
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 0, err)
        self.assertFalse((self.home / ".npmrc").exists())
        (backup,) = self.backups()
        self.assertEqual((backup / ".npmrc").read_text(), f"prefix={self.home}/.local\n")

    def test_npmrc_with_other_settings_stays_and_warns(self):
        text = f"prefix={self.home}/.local\nfund=false\n"
        (self.home / ".npmrc").write_text(text)
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 0, err)
        self.assertEqual((self.home / ".npmrc").read_text(), text)
        self.assertIn("~/.npmrc setzt prefix=~/.local", err)

    def test_graft_version_mismatch_keeps_the_old_node(self):
        self.runner.add(
            (str(self.prefix / "bin/graft"), "--version"), Result([], 0, "graft 0.1.0\n", "")
        )
        rc, _, err = self.run_main("-y", "node")
        self.assertEqual(rc, 1)
        self.assertIn("erwartet 0.25.0", err)
        self.assertTrue((self.bin / "node").is_symlink())

    def test_wrong_command_after_the_move_is_reported(self):
        self.runner.add(("bash", "-lic", "command -v nvim"), Result([], 0, "/usr/bin/nvim\n", ""))
        rc, _, err = self.run_main("-y", "neovim")
        self.assertEqual(rc, 1)
        self.assertIn(
            "nvim (/usr/bin/nvim) nicht auf Homebrew".replace(" nicht auf Homebrew", ""), err
        )

    def test_unknown_tool_and_missing_homebrew(self):
        with self.assertRaises(Fehler) as ctx:
            self.run_main("-y", "emacs")
        self.assertIn("unbekanntes Werkzeug emacs", str(ctx.exception))
        (self.prefix / "bin/brew").unlink()
        with self.assertRaises(Fehler) as ctx:
            self.run_main("-y")
        self.assertIn("Homebrew fehlt", str(ctx.exception))

    def test_without_terminal_needs_yes(self):
        before = self.snapshot(self.home)
        with self.assertRaises(Fehler) as ctx:
            self.run_main()
        self.assertIn("nur mit -y", str(ctx.exception))
        self.assertEqual(self.snapshot(self.home), before)


class TemplateTest(Fixture):
    def test_changed_template_is_an_error_and_nothing_changes(self):
        path = self.src / ".chezmoiignore"
        path.write_text(path.read_text().replace(migrate.IGNORE_OLD, "{{- if anders }}"))
        git(self.repo, "commit", "-aqm", "changed")
        before = (self.snapshot(self.home), self.snapshot(self.repo))
        with self.assertRaises(Fehler) as ctx:
            self.run_main("-y")
        self.assertIn("die Vorlage hat sich geändert", str(ctx.exception))
        self.assertEqual((self.snapshot(self.home), self.snapshot(self.repo)), before)

    def test_already_replaced_is_skipped(self):
        self.run_main("-y")
        count = git(self.repo, "rev-list", "--count", "HEAD")
        self.runner = self.new_runner(installed=True)
        self.run_main("-y", runner=self.runner)
        self.assertEqual(git(self.repo, "rev-list", "--count", "HEAD"), count)


class RollbackTest(Fixture):
    def test_rollback_restores_everything(self):
        before = self.snapshot(self.home / ".local/bin"), self.snapshot(self.home / ".local/opt")
        self.run_main("-y")
        rc, _, err = self.run_main("--rollback")
        self.assertEqual(rc, 0, err)
        self.assertEqual(
            (self.snapshot(self.home / ".local/bin"), self.snapshot(self.home / ".local/opt")),
            before,
        )
        self.assertTrue(
            (self.home / ".local/lib/node_modules/@nanonets/graft/package.json").exists()
        )

    def test_rollback_skips_an_occupied_place(self):
        self.run_main("-y")
        touch_exe(self.bin / "gh")
        rc, _, err = self.run_main("--rollback")
        self.assertEqual(rc, 1)
        self.assertIn("ist belegt", err)
        self.assertFalse((self.bin / "gh").is_symlink())
        self.assertTrue((self.bin / "nvim").is_symlink())
        (backup,) = self.backups()
        self.assertTrue((backup / ".local/bin/gh").is_symlink())

    def test_rollback_dry_run(self):
        self.run_main("-y")
        moved = self.snapshot(self.home)
        rc, out, _ = self.run_main("--rollback", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual(self.snapshot(self.home), moved)
        self.assertIn("würde zurückspielen:", out)

    def test_rollback_without_backup(self):
        with self.assertRaises(Fehler) as ctx:
            self.run_main("--rollback")
        self.assertIn("keine Sicherung", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

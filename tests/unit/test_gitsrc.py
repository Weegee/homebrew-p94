import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from p94brew import gitsrc
from p94brew.runner import Runner

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    # git commit starts a detached `git maintenance run --auto`; it can still write into .git while
    # the test removes the temporary repository ("Directory not empty").
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "maintenance.auto",
    "GIT_CONFIG_VALUE_0": "false",
}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    )
    return out.stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    return path


def commit_file(repo: Path, rel: str, text: str, message: str = "c") -> str:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


class GitSrcTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.runner = Runner(env={**os.environ, **GIT_ENV})
        self.repo = make_repo(self.root / "src")
        self.c1 = commit_file(self.repo, "packaging/homebrew/p94-demo.rb", "# one\n")
        git(self.repo, "tag", "v20261103.01")
        self.c2 = commit_file(self.repo, "packaging/homebrew/p94-demo.rb", "# two\n")
        git(self.repo, "tag", "-a", "-m", "release", "v20261104.02")
        git(self.repo, "tag", "latest")

    def test_list_tags_filters_and_peels(self):
        tags = {t.name: t.commit for t in gitsrc.list_tags(str(self.repo), self.runner)}
        self.assertEqual(set(tags), {"v20261103.01", "v20261104.02"})
        self.assertEqual(tags["v20261103.01"], self.c1)
        self.assertEqual(tags["v20261104.02"], self.c2)

    def test_newest(self):
        tags = gitsrc.list_tags(str(self.repo), self.runner)
        self.assertEqual(gitsrc.newest(tags).name, "v20261104.02")
        self.assertIsNone(gitsrc.newest([]))

    def test_newest_orders_by_number_within_a_day(self):
        tags = [gitsrc.Tag("v20261104.09", "a"), gitsrc.Tag("v20261104.10", "b")]
        self.assertEqual(gitsrc.newest(tags).name, "v20261104.10")

    def test_fetch_list_and_read(self):
        cache = self.root / "cache" / "src.git"
        gitsrc.fetch_tag(str(self.repo), "v20261104.02", cache, self.runner)
        self.assertEqual(gitsrc.list_templates(cache, "v20261104.02", self.runner), ["p94-demo"])
        self.assertEqual(
            gitsrc.read_template(cache, "v20261104.02", "p94-demo", self.runner), "# two\n"
        )
        # a second fetch of another tag into the same cache works
        gitsrc.fetch_tag(str(self.repo), "v20261103.01", cache, self.runner)
        self.assertEqual(
            gitsrc.read_template(cache, "v20261103.01", "p94-demo", self.runner), "# one\n"
        )

    def test_no_templates(self):
        repo = make_repo(self.root / "plain")
        commit_file(repo, "README", "x\n")
        git(repo, "tag", "v20261104.01")
        cache = self.root / "cache" / "plain.git"
        gitsrc.fetch_tag(str(repo), "v20261104.01", cache, self.runner)
        self.assertEqual(gitsrc.list_templates(cache, "v20261104.01", self.runner), [])

    def test_missing_repository(self):
        with self.assertRaises(gitsrc.RepoNotFound):
            gitsrc.list_tags(str(self.root / "nope"), self.runner)


if __name__ == "__main__":
    unittest.main()

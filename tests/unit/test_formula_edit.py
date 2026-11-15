import unittest

from p94brew import formula_edit as fe
from p94brew.cli import Fehler

SHA_A = "a" * 40
SHA_B = "b" * 40

MULTI = f"""\
class P94Demo < Formula
  desc "Demo"
  homepage "https://example.org"
  url "https://github.com/example/p94-demo.git",
      tag:      "v20261101.01",
      revision: "{SHA_A}"
  license "GPL-3.0-or-later"

  resource "extra" do
    url "https://example.org/extra.tar.gz"
    sha256 "{SHA_A}"
  end
end
"""

ONE = f"""\
class P94Demo < Formula
  url "https://github.com/example/p94-demo.git", tag: "v20261101.01", revision: "{SHA_A}"
  license "GPL-3.0-or-later"
end
"""


class GetSourceTest(unittest.TestCase):
    def test_multi_line(self):
        self.assertEqual(
            fe.get_source(MULTI),
            ("https://github.com/example/p94-demo.git", "v20261101.01", SHA_A),
        )

    def test_ignores_resources(self):
        self.assertEqual(fe.get_source(MULTI)[0], "https://github.com/example/p94-demo.git")

    def test_one_line(self):
        self.assertEqual(fe.get_source(ONE)[1:], ("v20261101.01", SHA_A))

    def test_no_url(self):
        with self.assertRaises(Fehler):
            fe.get_source("class X < Formula\nend\n")


class SetSourceTest(unittest.TestCase):
    def test_multi_line(self):
        out = fe.set_source(MULTI, "https://github.com/example/p94-demo.git", "v20261104.02", SHA_B)
        self.assertIn('tag:      "v20261104.02"', out)
        self.assertIn(f'revision: "{SHA_B}"', out)
        self.assertNotIn("v20261101.01", out)
        self.assertIn('url "https://example.org/extra.tar.gz"', out)
        self.assertNotIn("using:", out)

    def test_one_line(self):
        out = fe.set_source(ONE, "https://x/y.git", "v20261104.02", SHA_B)
        self.assertIn(f'url "https://x/y.git", tag: "v20261104.02", revision: "{SHA_B}"', out)

    def test_missing_tag(self):
        text = f'class X < Formula\n  url "https://x/y.git", revision: "{SHA_A}"\nend\n'
        with self.assertRaises(Fehler) as ctx:
            fe.set_source(text, "https://x/y.git", "v20261104.02", SHA_B)
        self.assertIn("tag: und revision:", str(ctx.exception))

    def test_local_path_one_line_gets_using_git(self):
        out = fe.set_source(ONE, "/tmp/src", "v20261104.02", SHA_B)
        self.assertIn('url "/tmp/src", using: :git, tag: "v20261104.02"', out)

    def test_local_path_multi_line_gets_using_git(self):
        out = fe.set_source(MULTI, "/tmp/src", "v20261104.02", SHA_B)
        self.assertIn('url "/tmp/src",\n      using:    :git,\n      tag:      "v20261104.02"', out)

    def test_local_path_keeps_existing_using(self):
        text = ONE.replace('", tag:', '", using: :git, tag:')
        out = fe.set_source(text, "/tmp/src", "v20261104.02", SHA_B)
        self.assertEqual(out.count("using:"), 1)

    def test_rejects_bad_tag_and_revision(self):
        with self.assertRaises(Fehler):
            fe.set_source(MULTI, "https://x", "latest", SHA_B)
        with self.assertRaises(Fehler):
            fe.set_source(MULTI, "https://x", "v20261104.02", "abc")


class TrySourceTest(unittest.TestCase):
    def test_removes_tag_and_sets_version(self):
        out = fe.set_try_source(MULTI, "/tmp/src", SHA_B, "20261104.02")
        self.assertIn(
            f'  url "/tmp/src", using: :git, revision: "{SHA_B}"\n  version "20261104.02"\n', out
        )
        self.assertNotIn("tag:", out)
        self.assertIn('license "GPL-3.0-or-later"', out)
        self.assertIn('url "https://example.org/extra.tar.gz"', out)


if __name__ == "__main__":
    unittest.main()

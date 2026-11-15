import tarfile
import tempfile
import unittest
from pathlib import Path

from p94brew import pacmandb as pdb

from .steamos_fixture import desc_text, make_system

GLIBC = desc_text(
    "glibc",
    "2.43-1",
    sha="a" * 64,
    depends=["linux-api-headers>=4.10", "tzdata"],
    licenses=["GPL-2.0-or-later", "LGPL-2.1-or-later"],
)


class ParseTest(unittest.TestCase):
    def test_parse_desc(self):
        d = pdb.parse_desc(GLIBC, "core-3.9")
        self.assertEqual(d.name, "glibc")
        self.assertEqual(d.version, "2.43-1")
        self.assertEqual(d.filename, "glibc-2.43-1-x86_64.pkg.tar.zst")
        self.assertEqual(d.sha256, "a" * 64)
        self.assertEqual(d.depends, ("linux-api-headers>=4.10", "tzdata"))
        self.assertEqual(d.licenses, ("GPL-2.0-or-later", "LGPL-2.1-or-later"))
        self.assertEqual(d.repo, "core-3.9")

    def test_missing_fields_are_empty(self):
        d = pdb.parse_desc("%NAME%\nx\n\n%VERSION%\n1-1\n", "local")
        self.assertEqual((d.filename, d.sha256, d.depends, d.provides), ("", "", (), ()))

    def test_dep_name(self):
        self.assertEqual(pdb.dep_name("libcap.so=2-64"), "libcap.so")
        self.assertEqual(pdb.dep_name("linux-api-headers>=4.10"), "linux-api-headers")
        self.assertEqual(pdb.dep_name("tzdata"), "tzdata")

    def test_package_url(self):
        url = pdb.package_url("https://m/archlinux-mirror/$repo/os/$arch", "core-3.9", "a-1.zst")
        self.assertEqual(url, "https://m/archlinux-mirror/core-3.9/os/x86_64/a-1.zst")


class FilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.system = make_system(
            self.root,
            sync={
                "core-3.9": [GLIBC],
                "extra-3.9": [desc_text("ethtool", "1:7.1-1", sha="b" * 64)],
            },
            local=[
                desc_text("glibc", "2.43-1"),
                desc_text("libmnl", "1.0.5-2", provides=["libmnl.so=0-64"]),
            ],
        )

    def test_read_sync_db(self):
        db = pdb.read_sync_db(self.system.db_dir / "sync/core-3.9.db", "core-3.9")
        self.assertEqual(set(db), {"glibc"})
        self.assertEqual(db["glibc"].sha256, "a" * 64)
        db = pdb.read_sync_db(self.system.db_dir / "sync/extra-3.9.db", "extra-3.9")
        self.assertEqual(db["ethtool"].version, "1:7.1-1")
        self.assertEqual(db["ethtool"].filename, "ethtool-1:7.1-1-x86_64.pkg.tar.zst")

    def test_read_local_db(self):
        local = pdb.read_local_db(self.system.db_dir / "local")
        self.assertEqual(set(local), {"glibc", "libmnl"})
        self.assertEqual(local["libmnl"].provides, ("libmnl.so=0-64",))
        self.assertEqual(local["glibc"].repo, "local")

    def test_repos_from_pacman_conf(self):
        self.assertEqual(
            pdb.repos_from_pacman_conf(self.system.pacman_conf), ["core-3.9", "extra-3.9"]
        )

    def test_mirror_template(self):
        self.assertIn("$repo", pdb.mirror_template(self.system.mirrorlist))

    def test_os_build_id(self):
        self.assertEqual(pdb.os_build_id(self.system.os_release), "20261023.100")

    def test_sync_db_must_be_a_tar(self):
        bad = self.root / "bad.db"
        bad.write_text("nope")
        with self.assertRaises(tarfile.TarError):
            pdb.read_sync_db(bad, "x")


if __name__ == "__main__":
    unittest.main()

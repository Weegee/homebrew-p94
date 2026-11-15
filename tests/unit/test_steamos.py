import tempfile
import unittest
from pathlib import Path

from p94brew import steamos
from p94brew.cli import Fehler

from .steamos_fixture import desc_text, make_system

SYSROOT = """\
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

TOOLS = """\
formula = "steamos-tools"
desc = "Werkzeuge aus dem SteamOS-Spiegel"

[[package]]
name = "ethtool"
bin = ["ethtool"]
test = ["ethtool", "--version"]

[[package]]
name = "helper"
bin = ["helper-tool"]
"""

PYSIDE = """\
formula = "steamos-pyside"
desc = "PySide6 aus dem SteamOS-Spiegel für /usr/bin/python3"

[[package]]
name = "pyside6"
root = true

[[package]]
name = "shiboken6"
root = true
"""

SHA = {
    "glibc": "a" * 64,
    "linux-api-headers": "b" * 64,
    "ethtool": "c" * 64,
    "helper": "d" * 64,
    "pyside6": "e" * 64,
    "shiboken6": "f" * 64,
}

PYSIDE_PACKAGES = [
    desc_text(
        "pyside6",
        "6.11.1-4",
        sha=SHA["pyside6"],
        depends=["glibc", "shiboken6"],
        licenses=["LGPL-3.0-only"],
    ),
    desc_text(
        "shiboken6",
        "6.11.1-4",
        sha=SHA["shiboken6"],
        depends=["glibc"],
        licenses=["LGPL-3.0-only"],
    ),
]


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write_list(self, text: str, name: str = "list.toml") -> Path:
        path = self.root / name
        path.write_text(text)
        return path

    def system(self, sync_extra=None, local_extra=None, glibc_local="2.43+r37-1"):
        sync = {
            "core-3.9": [
                desc_text(
                    "glibc",
                    "2.43+r37-1",
                    sha=SHA["glibc"],
                    depends=["linux-api-headers>=4.10"],
                    licenses=["GPL-2.0-or-later"],
                ),
                desc_text(
                    "linux-api-headers",
                    "7.1-1",
                    sha=SHA["linux-api-headers"],
                    licenses=["GPL-2.0-only WITH Linux-syscall-note"],
                ),
            ],
            "extra-3.9": [
                desc_text(
                    "ethtool",
                    "1:7.1-1",
                    sha=SHA["ethtool"],
                    depends=["glibc", "libmnl"],
                    licenses=["GPL-2.0-or-later"],
                ),
                desc_text("helper", "1.0-1", sha=SHA["helper"], depends=["glibc", "ethtool"]),
            ],
        }
        sync["extra-3.9"] += sync_extra or []
        local = [
            desc_text("glibc", glibc_local),
            desc_text("linux-api-headers", "7.1-1"),
            desc_text("libmnl", "1.0.5-2"),
        ] + (local_extra or [])
        return make_system(self.root, sync, local)

    def resolve(self, text: str, **kw):
        lst = steamos.load_list(self.write_list(text))
        sync, repos, local, mirror, _ = self.system(**kw).load()
        return lst, steamos.resolve_list(lst, sync, repos, local, mirror)


class LoadListTest(Fixture):
    def test_valid(self):
        lst = steamos.load_list(self.write_list(SYSROOT))
        self.assertEqual(lst.formula, "steamos-sysroot")
        self.assertTrue(lst.gcc_links)
        self.assertEqual([p.name for p in lst.packages], ["glibc", "linux-api-headers"])
        self.assertTrue(lst.packages[0].headers)

    def assertBad(self, text: str, fragment: str):
        with self.assertRaises(Fehler) as ctx:
            steamos.load_list(self.write_list(text))
        self.assertIn("list.toml", str(ctx.exception))
        self.assertIn(fragment, str(ctx.exception))

    def test_missing_formula(self):
        self.assertBad('desc = "x"\n[[package]]\nname = "a"\nheaders = true\n', "'formula'")

    def test_package_without_headers_and_bin(self):
        self.assertBad(
            SYSROOT.replace("headers = true", "", 1), "braucht 'headers', 'bin' oder 'root'"
        )

    def test_root_must_be_bool(self):
        self.assertBad(PYSIDE.replace("root = true", 'root = "ja"', 1), "'root' in [[package]]")

    def test_root_valid(self):
        lst = steamos.load_list(self.write_list(PYSIDE))
        self.assertEqual([p.name for p in lst.packages], ["pyside6", "shiboken6"])
        self.assertTrue(all(p.root and not p.bin for p in lst.packages))

    def test_unknown_key(self):
        self.assertBad(SYSROOT + "bogus = 1\n", "unbekannter Schlüssel 'bogus'")
        self.assertBad(
            SYSROOT.replace("gcc_links = true", "gcc_links = true\nbogus = 1"), "'bogus'"
        )

    def test_desc_rules(self):
        self.assertBad(SYSROOT.replace("Kernel-Header aus SteamOS", "Header."), "'desc'")

    def test_test_must_start_with_bin(self):
        self.assertBad(
            TOOLS.replace('test = ["ethtool", "--version"]', 'test = ["other"]'), "'test'"
        )


class ResolveTest(Fixture):
    def test_resolves_urls_and_sha(self):
        _, resolved = self.resolve(SYSROOT)
        self.assertEqual(resolved[0].desc.sha256, SHA["glibc"])
        self.assertEqual(
            resolved[0].url,
            "https://mirror.example/archlinux-mirror/core-3.9/os/x86_64/glibc-2.43+r37-1-x86_64.pkg.tar.zst",
        )
        self.assertFalse(any(r.lib_wrapper for r in resolved))

    def test_missing_package(self):
        with self.assertRaises(Fehler) as ctx:
            self.resolve(SYSROOT.replace('"linux-api-headers"', '"nope"'))
        self.assertIn(
            "Paket nope steht in keiner Paketdatenbank (core-3.9, extra-3.9)", str(ctx.exception)
        )

    def test_version_conflict_with_image(self):
        with self.assertRaises(Fehler) as ctx:
            self.resolve(SYSROOT, glibc_local="2.42-1")
        self.assertIn(
            "glibc: Paketdatenbank hat 2.43+r37-1, das System 2.42-1; "
            "erst SteamOS-Update abschließen oder neu starten",
            str(ctx.exception),
        )

    def test_unmet_dependency(self):
        text = 'formula = "t"\ndesc = "x"\n[[package]]\nname = "needs-more"\nbin = ["x"]\n'
        extra = [desc_text("needs-more", "1-1", sha="e" * 64, depends=["missing-lib"])]
        with self.assertRaises(Fehler) as ctx:
            self.resolve(text, sync_extra=extra)
        self.assertIn(
            "needs-more braucht missing-lib, das weder im Abbild noch in der Liste steht; "
            "missing-lib zur Liste hinzufügen",
            str(ctx.exception),
        )

    def test_dependency_from_the_list_needs_wrapper(self):
        _, resolved = self.resolve(TOOLS)
        by_name = {r.package.name: r for r in resolved}
        self.assertFalse(by_name["ethtool"].lib_wrapper)
        self.assertTrue(by_name["helper"].lib_wrapper)

    def test_provides_satisfy_dependencies(self):
        extra = [desc_text("lib-user", "1-1", sha="f" * 64, depends=["libfoo.so=1-64"])]
        local = [desc_text("libfoo-pkg", "1-1", provides=["libfoo.so=1-64"])]
        text = TOOLS.replace("helper", "lib-user")
        _, resolved = self.resolve(text, sync_extra=extra, local_extra=local)
        self.assertFalse(resolved[1].lib_wrapper)


class RenderTest(Fixture):
    def render(self, text: str, version="20261023.100", revision=0, **kw):
        lst, resolved = self.resolve(text, **kw)
        return steamos.render(lst, resolved, version, revision)

    def test_class_name(self):
        self.assertEqual(steamos.class_name("steamos-sysroot"), "SteamosSysroot")
        self.assertEqual(steamos.class_name("steamos-tools"), "SteamosTools")

    def test_sysroot(self):
        out = self.render(SYSROOT)
        self.assertIn("class SteamosSysroot < Formula", out)
        self.assertIn("# Generated by brew p94-sync from", out)
        self.assertEqual(out.count("using: :nounzip"), 2)
        self.assertIn(f'sha256 "{SHA["glibc"]}"', out)
        self.assertIn('resource "linux-api-headers" do', out)
        self.assertIn('"./glibc-2.43+r37-1-x86_64.pkg.tar.zst"', out)
        self.assertIn("license :cannot_represent", out)
        self.assertIn('version "20261023.100"', out)
        self.assertNotIn("revision", out)
        self.assertIn('assert_path_exists libexec/"sysroot/usr/include/stdio.h"', out)
        self.assertIn('assert_path_exists libexec/"sysroot/usr/include/linux/version.h"', out)
        self.assertIn("gcc-[0-9]*", out)
        self.assertNotIn('depends_on "gcc"', out)
        self.assertNotIn("write_env_script", out)
        self.assertNotIn('root/"usr/bin"', out)

    def test_no_line_longer_than_118(self):
        for text in (SYSROOT, TOOLS, PYSIDE):
            for line in self.render(text, sync_extra=PYSIDE_PACKAGES).splitlines():
                self.assertLessEqual(len(line), 118, line)

    def test_root_only(self):
        out = self.render(PYSIDE, sync_extra=PYSIDE_PACKAGES)
        self.assertIn('root = libexec/"root"', out)
        self.assertEqual(out.count('"bsdtar"'), 2)
        self.assertEqual(out.count('"-C", root,'), 2)
        self.assertIn('resource "shiboken6" do', out)
        for absent in ("%w[", "install_symlink", "write_env_script", "man.install", "sysroot"):
            self.assertNotIn(absent, out.replace("%w[.PKGINFO", ""))
        self.assertEqual(out.count('assert_path_exists libexec/"root/usr"'), 1)

    def test_bin_and_root_extract_once(self):
        text = TOOLS.replace('bin = ["ethtool"]', 'bin = ["ethtool"]\nroot = true', 1)
        out = self.render(text)
        self.assertEqual(out.count('"bsdtar"'), 2)  # one per package, not two for ethtool
        self.assertNotIn('assert_path_exists libexec/"root/usr"', out)

    def test_tools(self):
        out = self.render(TOOLS)
        self.assertEqual(out.count('resource "'), 1)
        self.assertNotIn("gcc", out)
        self.assertIn("%w[ethtool].each do |cmd|", out)
        self.assertIn("bin.install_symlink src => cmd", out)
        self.assertIn('(bin/cmd).write_env_script src, LD_LIBRARY_PATH: root/"usr/lib"', out)
        self.assertIn('system bin/"ethtool", "--version"', out)
        self.assertIn('assert_predicate bin/"helper-tool", :executable?', out)
        self.assertIn("--exclude", out)

    def test_revision_line(self):
        self.assertIn("  revision 2\n", self.render(SYSROOT, revision=2))


class GenerateTest(Fixture):
    def parts(self, text=SYSROOT):
        return self.resolve(text)

    def test_new_formula(self):
        lst, resolved = self.parts()
        text = steamos.generate(lst, resolved, "20261023.100", None)
        self.assertEqual(steamos.version_label(text), "20261023.100")

    def test_unchanged_gives_none(self):
        lst, resolved = self.parts()
        text = steamos.generate(lst, resolved, "20261023.100", None)
        self.assertIsNone(steamos.generate(lst, resolved, "20261023.100", text))
        # a new build id alone does not regenerate
        self.assertIsNone(steamos.generate(lst, resolved, "20261030.101", text))

    def test_changed_content_with_same_version_bumps_revision(self):
        lst, resolved = self.parts()
        old = steamos.generate(lst, resolved, "20261023.100", None)
        lst2, resolved2 = self.resolve(SYSROOT.replace("Kernel-Header", "Linux-Header"))
        new = steamos.generate(lst2, resolved2, "20261023.100", old)
        self.assertEqual(steamos.read_version(new), ("20261023.100", 1))
        self.assertEqual(steamos.version_label(new), "20261023.100_1")
        newer = steamos.generate(
            lst2, resolved2, "20261023.100", new.replace("Linux-Header", "X-Header")
        )
        self.assertEqual(steamos.read_version(newer), ("20261023.100", 2))

    def test_changed_content_with_new_build_id_resets_revision(self):
        lst, resolved = self.parts()
        old = steamos.generate(lst, resolved, "20261023.100", None)
        lst2, resolved2 = self.resolve(SYSROOT.replace("Kernel-Header", "Linux-Header"))
        new = steamos.generate(lst2, resolved2, "20261030.101", old)
        self.assertEqual(steamos.read_version(new), ("20261030.101", 0))
        self.assertNotIn("revision", new)

    def test_strip_version_lines(self):
        text = 'a\n  version "1"\n  revision 2\nb\n'
        self.assertEqual(steamos.strip_version_lines(text), "a\nb\n")


if __name__ == "__main__":
    unittest.main()

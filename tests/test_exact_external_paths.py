import os
import shutil
import unittest
from pathlib import Path
from support import BundleCase

class ExactExternalPathTests(BundleCase):
    def setUp(self):
        super().setUp()
        self.file("CMakeLists.txt", "project(example)\n")
        self.file("src/main.py", "print('main')\n")
        self.file("src/extra.py", "print('extra')\n")
        self.external = self.work / "external.txt"
        self.external.write_text("external\n", encoding="utf-8")

    def test_exact_and_path_glob(self):
        exact = self.work / "exact.md"
        glob = self.work / "glob.md"
        r1 = self.cli(self.root, "-p", "./CMakeLists.txt", "--encoding", "*:utf-8", "-o", exact)
        r2 = self.cli(self.root, "-p", "src/*.py", "--encoding", "*:utf-8", "-o", glob)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(self.entries(exact), ["CMakeLists.txt"])
        self.assertEqual(self.entries(glob), ["src/extra.py", "src/main.py"])

    def test_relative_and_absolute_external_input_store_relative_path(self):
        outputs = [self.work / "relative.md", self.work / "absolute.md"]
        inputs = ["../external.txt", self.external.resolve()]
        for source, output in zip(inputs, outputs):
            result = self.cli(self.root, "-p", source, "--encoding", "*:utf-8", "-o", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.entries(output), ["../external.txt"])
            self.assertEqual(self.fields(output, "Key"), ["e:../external.txt"])
            self.assertNotIn(str(self.external.resolve()), self.text(output))

    def test_real_magic_like_names_do_not_conflict(self):
        self.file("__external__/__parent__/external.txt", "internal\n")
        output = self.work / "collision.md"
        result = self.cli(self.root, "-p", "__external__/__parent__/external.txt",
                          "-p", "../external.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fields(output, "Key"), [
            "e:../external.txt", "i:__external__/__parent__/external.txt"
        ])

    def test_external_path_only_is_not_in_manifest(self):
        output = self.work / "paths.md"
        result = self.cli(self.root, "-p", self.external.resolve(),
                          "--paths-only", self.external.resolve(), "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# path only", self.text(output))
        self.assertEqual(self.manifest(output), [])

    @unittest.skipUnless(shutil.which("git"), "git unavailable")
    def test_repository_relative_path_is_saved(self):
        repo = self.work / "repo"
        project = repo / "project"
        trash = repo / "trash"
        project.mkdir(parents=True); trash.mkdir()
        (trash / "file.txt").write_text("trash\n", encoding="utf-8")
        self.init_git(repo)
        output = self.work / "repo.md"
        result = self.cli(project, "-p", "../trash/file.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Path: "../trash/file.txt"', self.text(output))
        self.assertIn('Repository path: "trash/file.txt"', self.text(output))

    @unittest.skipUnless(os.name == "posix", "POSIX filenames only")
    def test_colon_is_encoded_not_removed(self):
        (self.work / "a:b.txt").write_text("colon\n", encoding="utf-8")
        (self.work / "ab.txt").write_text("plain\n", encoding="utf-8")
        output = self.work / "colon.md"
        result = self.cli(self.root, "-p", "../a:b.txt", "-p", "../ab.txt",
                          "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fields(output, "Key"), ["e:../a%3Ab.txt", "e:../ab.txt"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_keeps_link_name(self):
        target = self.work / "target.txt"; target.write_text("link\n", encoding="utf-8")
        link = self.root / "linked.txt"
        try: link.symlink_to(target)
        except OSError as exc: self.skipTest(str(exc))
        output = self.work / "link.md"
        result = self.cli(self.root, "-p", "./linked.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.entries(output), ["linked.txt"])

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_cross_drive_is_rejected(self):
        with self.assertRaises(Exception):
            import bundle_paths
            bundle_paths.make_archive_path(Path("D:/project"), Path("C:/temp/file.txt"))

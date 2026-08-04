import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCRIPT = REPO_ROOT / "bundle.py"
SPEC = importlib.util.spec_from_file_location("bundle_module", BUNDLE_SCRIPT)
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)


class ExactExternalPathTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.project = self.workspace / "project"
        self.project.mkdir()
        (self.project / "CMakeLists.txt").write_text("project(example)\n", encoding="utf-8")
        (self.project / "src").mkdir()
        (self.project / "src" / "main.py").write_text("print('main')\n", encoding="utf-8")
        (self.project / "src" / "extra.py").write_text("print('extra')\n", encoding="utf-8")
        self.external = self.workspace / "external.txt"
        self.external.write_text("внешний файл\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_bundle(self, *args):
        return subprocess.run(
            [sys.executable, str(BUNDLE_SCRIPT), *map(str, args)],
            cwd=str(self.workspace),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    @staticmethod
    def read_entries(output_path):
        entries = []
        for line in output_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## `"):
                entry = line[4:].split("`", 1)[0].replace("\\", "/")
                if entry not in entries:
                    entries.append(entry)
        return entries

    def test_version_option_uses_single_source_value(self):
        result = self.run_bundle("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"bundle.py {BUNDLE.__version__}")

    def test_version_metadata_is_written_on_create_and_append(self):
        output = self.workspace / "versioned.md"
        create_result = self.run_bundle(
            self.project,
            "-p", "./CMakeLists.txt",
            "--encoding", "*:utf-8",
            "-o", output,
        )
        append_result = self.run_bundle(
            self.project,
            "-p", "src/main.py",
            "--encoding", "*:utf-8",
            "-a", output,
        )

        self.assertEqual(create_result.returncode, 0, create_result.stderr)
        self.assertEqual(append_result.returncode, 0, append_result.stderr)
        text = output.read_text(encoding="utf-8")
        metadata = f"<!-- bundle:version={BUNDLE.__version__} -->"
        heading = f"# Bundle {BUNDLE.__version__} from `"
        self.assertEqual(text.count(metadata), 2)
        self.assertEqual(text.count(heading), 2)
        self.assertIn(f"bundle.py {BUNDLE.__version__}", create_result.stderr)
        self.assertIn(f"bundle.py {BUNDLE.__version__}", append_result.stderr)
        self.assertEqual(self.read_entries(output), ["CMakeLists.txt", "src/main.py"])

    def test_dot_slash_selects_exact_root_file(self):
        output = self.workspace / "dot.md"
        result = self.run_bundle(self.project, "-p", "./CMakeLists.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_entries(output), ["CMakeLists.txt"])

    def test_path_glob_is_not_classified_as_exact(self):
        output = self.workspace / "glob.md"
        result = self.run_bundle(self.project, "-p", "src/*.py", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_entries(output), ["src/extra.py", "src/main.py"])

    def test_parent_and_absolute_path_use_same_safe_archive_name(self):
        parent_output = self.workspace / "parent.md"
        absolute_output = self.workspace / "absolute.md"
        parent_result = self.run_bundle(self.project, "-p", "../external.txt", "--encoding", "*:utf-8", "-o", parent_output)
        absolute_result = self.run_bundle(self.project, "-p", self.external.resolve(), "--encoding", "*:utf-8", "-o", absolute_output)
        self.assertEqual(parent_result.returncode, 0, parent_result.stderr)
        self.assertEqual(absolute_result.returncode, 0, absolute_result.stderr)
        expected = ["__external__/__parent__/external.txt"]
        self.assertEqual(self.read_entries(parent_output), expected)
        self.assertEqual(self.read_entries(absolute_output), expected)
        self.assertIn("внешний файл", parent_output.read_text(encoding="utf-8"))

    def test_absolute_path_modifier_is_parsed_from_the_right(self):
        parsed = BUNDLE.parse_key_value_option(r"C:\temp\file.txt:cp1251", requires_value=True)
        self.assertEqual(parsed, [("C:/temp/file.txt", "cp1251")])
        flag = BUNDLE.parse_key_value_option(r"C:\temp\file.txt")
        self.assertEqual(flag, [("C:/temp/file.txt", True)])

    def test_external_path_can_be_used_in_paths_only_modifier(self):
        output = self.workspace / "paths-only.md"
        result = self.run_bundle(
            self.project,
            "-p", self.external.resolve(),
            "--paths-only", self.external.resolve(),
            "-o", output,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = output.read_text(encoding="utf-8")
        self.assertIn("# path only", text)
        self.assertNotIn("внешний файл", text)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_symlink_keeps_link_name_in_bundle(self):
        target = self.workspace / "target.txt"
        target.write_text("через ссылку\n", encoding="utf-8")
        link = self.project / "linked.txt"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symbolic link cannot be created: {exc}")

        output = self.workspace / "symlink.md"
        result = self.run_bundle(self.project, "-p", "./linked.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_entries(output), ["linked.txt"])
        self.assertIn("через ссылку", output.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "Windows-specific cross-drive behavior")
    def test_cross_drive_archive_name_does_not_call_relpath_across_drives(self):
        archive_path = BUNDLE.make_archive_path(Path("D:/project"), Path("C:/temp/file.txt"))
        self.assertEqual(archive_path.as_posix(), "__external__/C/temp/file.txt")


if __name__ == "__main__":
    unittest.main()

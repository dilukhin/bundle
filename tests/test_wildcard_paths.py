import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCRIPT = REPO_ROOT / "bundle.py"


class WildcardPathTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.project = self.workspace / "project"
        self.project.mkdir()

        files = {
            "tests/fixtures/source_event_v1/valid/a.json": '{"name": "а"}\n',
            "tests/fixtures/source_event_v1/valid/b.json": '{"name": "б"}\n',
            "tests/fixtures/source_event_v1/valid/nested.json": '{"name": "в"}\n',
            "tests/fixtures/source_event_v1/invalid/c.json": '{"error": "г"}\n',
            "tests/fixtures/source_event_v1/nested/deeper/d.json": '{"name": "д"}\n',
            "tests/fixtures/source_event_v1/valid/readme.txt": "текст\n",
            "single.txt": "один\n",
        }
        for relative_path, content in files.items():
            path = self.project / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        (self.project / "tests/fixtures/source_event_v1/valid/subdir").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_bundle(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(BUNDLE_SCRIPT), *map(str, args)],
            cwd=str(cwd or self.workspace),
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
            if not line.startswith("## `"):
                continue
            entry = line[4:].split("`", 1)[0]
            if entry not in entries:
                entries.append(entry)
        return entries

    def run_patterns_file(self, patterns, filename="patterns.txt", cwd=None, root=None):
        work_dir = Path(cwd or self.workspace)
        patterns_path = work_dir / filename
        patterns_path.write_text("\n".join(patterns) + "\n", encoding="utf-8")
        output_path = work_dir / (filename + ".md")
        result = self.run_bundle(
            root or self.project,
            "--patterns-file",
            patterns_path.name if patterns_path.parent == work_dir else patterns_path,
            "--encoding",
            "*:utf-8",
            "-o",
            output_path,
            cwd=work_dir,
        )
        return result, output_path

    def test_patterns_file_expands_valid_and_invalid_json_wildcards(self):
        result, output = self.run_patterns_file([
            "tests/fixtures/source_event_v1/valid/*.json",
            "tests/fixtures/source_event_v1/invalid/*.json",
        ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_entries(output), [
            "tests/fixtures/source_event_v1/invalid/c.json",
            "tests/fixtures/source_event_v1/valid/a.json",
            "tests/fixtures/source_event_v1/valid/b.json",
            "tests/fixtures/source_event_v1/valid/nested.json",
        ])

    def test_windows_separators_in_patterns_file(self):
        result, output = self.run_patterns_file([
            r"tests\fixtures\source_event_v1\valid\*.json",
            r"tests\fixtures\source_event_v1\invalid\*.json",
        ], filename="patterns-win.txt")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.read_entries(output)), 4)
        self.assertIn("tests/fixtures/source_event_v1/valid/*.json (3)", result.stderr)

    def test_no_match_is_visible_and_returns_error_when_nothing_selected(self):
        result, output = self.run_patterns_file([
            "tests/fixtures/source_event_v1/missing/*.json",
        ], filename="patterns-missing.txt")

        self.assertEqual(result.returncode, 1)
        self.assertFalse(output.exists())
        self.assertIn("tests/fixtures/source_event_v1/missing/*.json (0)", result.stderr)
        self.assertIn("(не найдено)", result.stderr)

    def test_question_mark_character_class_and_recursive_double_star(self):
        cases = [
            ("tests/fixtures/source_event_v1/valid/?.json", [
                "tests/fixtures/source_event_v1/valid/a.json",
                "tests/fixtures/source_event_v1/valid/b.json",
            ]),
            ("tests/fixtures/source_event_v1/valid/[ab].json", [
                "tests/fixtures/source_event_v1/valid/a.json",
                "tests/fixtures/source_event_v1/valid/b.json",
            ]),
            ("tests/fixtures/source_event_v1/**/*.json", [
                "tests/fixtures/source_event_v1/invalid/c.json",
                "tests/fixtures/source_event_v1/nested/deeper/d.json",
                "tests/fixtures/source_event_v1/valid/a.json",
                "tests/fixtures/source_event_v1/valid/b.json",
                "tests/fixtures/source_event_v1/valid/nested.json",
            ]),
        ]

        for index, (pattern, expected) in enumerate(cases):
            with self.subTest(pattern=pattern):
                result, output = self.run_patterns_file([pattern], filename=f"glob-{index}.txt")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.read_entries(output), expected)

    def test_single_star_in_path_does_not_cross_directory_boundary(self):
        result, output = self.run_patterns_file([
            "tests/fixtures/source_event_v1/*/*.json",
        ], filename="single-star.txt")

        self.assertEqual(result.returncode, 0, result.stderr)
        entries = self.read_entries(output)
        self.assertNotIn("tests/fixtures/source_event_v1/nested/deeper/d.json", entries)
        self.assertEqual(entries, [
            "tests/fixtures/source_event_v1/invalid/c.json",
            "tests/fixtures/source_event_v1/valid/a.json",
            "tests/fixtures/source_event_v1/valid/b.json",
            "tests/fixtures/source_event_v1/valid/nested.json",
        ])

    def test_single_file_directory_and_mixed_patterns(self):
        result, output = self.run_patterns_file([
            "single.txt",
            "tests/fixtures/source_event_v1/valid/",
            "tests/fixtures/source_event_v1/invalid/*.json",
        ], filename="mixed.txt")

        self.assertEqual(result.returncode, 0, result.stderr)
        entries = self.read_entries(output)
        self.assertIn("single.txt", entries)
        self.assertIn("tests/fixtures/source_event_v1/valid/", entries)
        self.assertIn("tests/fixtures/source_event_v1/invalid/c.json", entries)

    def test_wildcard_and_explicit_files_produce_equivalent_file_set(self):
        wildcard_result, wildcard_output = self.run_patterns_file([
            "tests/fixtures/source_event_v1/valid/*.json",
        ], filename="wildcard.txt")
        explicit_result, explicit_output = self.run_patterns_file([
            "tests/fixtures/source_event_v1/valid/a.json",
            "tests/fixtures/source_event_v1/valid/b.json",
            "tests/fixtures/source_event_v1/valid/nested.json",
        ], filename="explicit.txt")

        self.assertEqual(wildcard_result.returncode, 0, wildcard_result.stderr)
        self.assertEqual(explicit_result.returncode, 0, explicit_result.stderr)
        self.assertEqual(self.read_entries(wildcard_output), self.read_entries(explicit_output))

    def test_order_is_stable_and_sorted(self):
        runs = []
        for index in range(3):
            result, output = self.run_patterns_file([
                "tests/fixtures/source_event_v1/valid/*.json",
            ], filename=f"stable-{index}.txt")
            self.assertEqual(result.returncode, 0, result.stderr)
            runs.append(self.read_entries(output))

        self.assertEqual(runs[0], sorted(runs[0]))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])

    def test_run_from_another_working_directory(self):
        runner = self.workspace / "runner"
        runner.mkdir()
        result, output = self.run_patterns_file(
            ["tests/fixtures/source_event_v1/valid/*.json"],
            filename="patterns.txt",
            cwd=runner,
            root=Path("../project"),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.read_entries(output)), 3)


if __name__ == "__main__":
    unittest.main()

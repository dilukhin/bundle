from pathlib import Path
from support import BundleCase

class WildcardPathTests(BundleCase):
    def setUp(self):
        super().setUp()
        for name in [
            "tests/data/valid/a.json", "tests/data/valid/b.json",
            "tests/data/valid/nested.json", "tests/data/invalid/c.json",
            "tests/data/nested/deeper/d.json",
        ]:
            self.file(name, name + "\n")
        self.file("tests/data/valid/readme.txt")
        self.file("single.txt")
        (self.root / "tests/data/valid/subdir").mkdir()

    def patterns(self, values, name="patterns.txt", cwd=None, root=None):
        base = Path(cwd or self.work)
        source = base / name
        source.write_text("\n".join(values) + "\n", encoding="utf-8")
        output = base / (name + ".md")
        result = self.cli(root or self.root, "--patterns-file", source.name,
                          "--encoding", "*:utf-8", "-o", output, cwd=base)
        return result, output

    def test_path_wildcards_and_windows_separators(self):
        result, output = self.patterns([
            r"tests\data\valid\*.json", "tests/data/invalid/*.json"
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.entries(output), [
            "tests/data/invalid/c.json", "tests/data/valid/a.json",
            "tests/data/valid/b.json", "tests/data/valid/nested.json",
        ])
        self.assertIn("tests/data/valid/*.json (3)", result.stderr)

    def test_empty_match_creates_valid_empty_bundle(self):
        result, output = self.patterns(["tests/data/missing/*.json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Included files count: 0", self.text(output))
        self.assertIn("(не найдено)", result.stderr)

    def test_question_class_and_double_star(self):
        cases = {
            "tests/data/valid/?.json": ["tests/data/valid/a.json", "tests/data/valid/b.json"],
            "tests/data/valid/[ab].json": ["tests/data/valid/a.json", "tests/data/valid/b.json"],
            "tests/data/**/*.json": [
                "tests/data/invalid/c.json", "tests/data/nested/deeper/d.json",
                "tests/data/valid/a.json", "tests/data/valid/b.json",
                "tests/data/valid/nested.json",
            ],
        }
        for index, (pattern, expected) in enumerate(cases.items()):
            with self.subTest(pattern=pattern):
                result, output = self.patterns([pattern], f"case-{index}.txt")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.entries(output), expected)

    def test_single_star_does_not_cross_directory(self):
        result, output = self.patterns(["tests/data/*/*.json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("tests/data/nested/deeper/d.json", self.entries(output))

    def test_mixed_patterns_and_stable_order(self):
        values = ["single.txt", "tests/data/valid/", "tests/data/invalid/*.json"]
        first, out1 = self.patterns(values, "one.txt")
        second, out2 = self.patterns(values, "two.txt")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.entries(out1), self.entries(out2))
        self.assertEqual(self.entries(out1), sorted(self.entries(out1)))

    def test_run_from_another_directory(self):
        runner = self.work / "runner"
        runner.mkdir()
        result, output = self.patterns(["tests/data/valid/*.json"], cwd=runner,
                                       root=Path("../project"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.entries(output)), 3)

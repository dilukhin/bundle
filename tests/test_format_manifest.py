import hashlib
from support import BundleCase


class FormatManifestTests(BundleCase):
    def test_empty_bundle_and_required_markers(self):
        output = self.work / "empty.md"
        result = self.cli(self.root, "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(output)
        self.assertIn("<!-- bundle:format=2 -->", text)
        self.assertIn("Included files count: 0", text)
        self.assertEqual(self.manifest(output), [])

    def test_manifest_hashes_original_text_and_binary_bytes(self):
        text_bytes = b"hello\r\n"
        binary_bytes = b"\x00\x01\xff"
        (self.root / "text.txt").write_bytes(text_bytes)
        (self.root / "binary.bin").write_bytes(binary_bytes)
        output = self.work / "hash.md"
        result = self.cli(self.root, "-p", "text.txt,binary.bin",
                          "--encoding", "text.txt:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest(output), [
            f"{hashlib.sha256(binary_bytes).hexdigest()}  i:binary.bin",
            f"{hashlib.sha256(text_bytes).hexdigest()}  i:text.txt",
        ])
        self.assertIn("AAH/", self.text(output))

    def test_paths_only_is_counted_but_not_hashed(self):
        self.file("content.txt", "content\n")
        self.file("path.txt", "hidden\n")
        output = self.work / "paths.md"
        result = self.cli(self.root, "-p", "content.txt,path.txt",
                          "--paths-only", "path.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(output)
        self.assertIn("Included files count: 2", text)
        self.assertEqual(len(self.manifest(output)), 1)
        self.assertNotIn("hidden", text)

    def test_no_metadata_and_no_manifest_keep_fragment_identity(self):
        self.file("one.txt")
        output = self.work / "minimal.md"
        result = self.cli(self.root, "-p", "one.txt", "--encoding", "*:utf-8",
                          "--no-metadata", "--no-manifest", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(output)
        self.assertIn("bundle:fragment:start", text)
        self.assertIn("bundle:generator=bundle.py version=0.2.0", text)
        self.assertNotIn("Bundle metadata", text)
        self.assertNotIn("Bundle manifest", text)

    def test_append_creates_independent_fragments(self):
        self.file("a.txt", "a\n"); self.file("b.txt", "b\n")
        output = self.work / "append.md"
        first = self.cli(self.root, "-p", "a.txt", "--encoding", "*:utf-8", "-o", output)
        second = self.cli(self.root, "-p", "b.txt", "--encoding", "*:utf-8", "-a", output)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        text = self.text(output)
        self.assertEqual(text.count("bundle:fragment:start"), 2)
        self.assertEqual(text.count("bundle:manifest:start"), 2)
        self.assertIn("i:a.txt", text); self.assertIn("i:b.txt", text)

    def test_stdout_output(self):
        self.file("one.txt")
        result = self.cli(self.root, "-p", "one.txt", "--encoding", "*:utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<!-- bundle:fragment:start -->", result.stdout)
        self.assertIn("i:one.txt", result.stdout)

    def test_restoration_marks_exact_and_lossy_text(self):
        samples = {
            "bom.txt": b"\xef\xbb\xbftext\n",
            "cp1251.txt": "текст\n".encode("cp1251"),
            "crlf.txt": b"text\r\n",
            "exact.txt": b"text\n",
            "no-newline.txt": b"text",
        }
        for name, raw in samples.items():
            (self.root / name).write_bytes(raw)

        output = self.work / "restoration.md"
        result = self.cli(
            self.root,
            "-p", ",".join(samples),
            "--encoding", "bom.txt:utf-8-sig",
            "--encoding", "cp1251.txt:cp1251",
            "--encoding", "crlf.txt:utf-8",
            "--encoding", "exact.txt:utf-8",
            "--encoding", "no-newline.txt:utf-8",
            "-o", output,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fields(output, "Restoration"), [
            "lossy", "exact", "lossy", "exact", "lossy"
        ])
        self.assertEqual(len(self.manifest(output)), 5)

        without_backup = self.work / "without-backup.md"
        result = self.cli(
            self.root, "-p", "cp1251.txt", "--encoding", "cp1251.txt:cp1251",
            "--no-binary-backup", "cp1251.txt", "-o", without_backup,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(without_backup)
        self.assertEqual(self.fields(without_backup, "Restoration"), ["lossy"])
        self.assertNotIn("### Original bytes", text)

    def test_markdown_content_uses_longer_fence(self):
        content = "# Nested\n\n```python\nprint('x')\n```\n\n````\nexample\n````\n"
        self.file("nested.md", content)
        output = self.work / "nested-bundle.md"
        result = self.cli(
            self.root, "-p", "nested.md", "--encoding", "nested.md:utf-8", "-o", output
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(output)
        self.assertIn("`````md\n" + content + "`````\n", text)
        self.assertEqual(self.fields(output, "Restoration"), ["exact"])

    def test_paths_with_spaces_and_unicode_are_stable(self):
        raw = "данные\n".encode("utf-8")
        path = self.root / "каталог" / "file name.txt"
        path.parent.mkdir()
        path.write_bytes(raw)
        output = self.work / "unicode.md"
        result = self.cli(
            self.root, "-p", "каталог/file name.txt",
            "--encoding", "каталог/file name.txt:utf-8", "-o", output,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(output)
        self.assertIn('Path: "каталог/file name.txt"', text)
        self.assertIn("i:%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3/file%20name.txt", text)
        self.assertEqual(self.manifest(output), [
            f"{hashlib.sha256(raw).hexdigest()}  i:%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3/file%20name.txt"
        ])

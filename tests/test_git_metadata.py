import shutil
import subprocess
import unittest
from pathlib import Path
from support import BundleCase

@unittest.skipUnless(shutil.which("git"), "git unavailable")
class GitMetadataTests(BundleCase):
    def commit(self):
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "initial"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_outside_git_records_absolute_root(self):
        self.file("one.txt")
        output = self.work / "plain.md"
        result = self.cli(self.root, "-p", "one.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(output)
        repository = [line.split(": ", 1)[1] for line in text.splitlines()
                      if line.startswith("Repository: ")][0]
        self.assertTrue(Path(repository).samefile(self.root))
        self.assertIn("Git status: not-a-git-repository", text)

    def test_clean_dirty_and_full_commit(self):
        self.file("one.txt")
        self.init_git(); self.commit()
        clean = self.work / "clean.md"
        result = self.cli(self.root, "-p", "one.txt", "--encoding", "*:utf-8", "-o", clean)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(clean)
        self.assertIn("Git status: clean", text)
        commit = [line for line in text.splitlines() if line.startswith("Commit: ")][0].split()[1]
        self.assertEqual(len(commit), 40)

        self.file("one.txt", "changed\n"); self.file("new.txt")
        dirty = self.work / "dirty.md"
        result = self.cli(self.root, "-p", "one.txt", "--encoding", "*:utf-8", "-o", dirty)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.text(dirty)
        self.assertIn("Git status: dirty", text)
        self.assertIn(" M one.txt", text)
        self.assertIn("?? new.txt", text)

    def test_detached_head_is_explicit(self):
        self.file("one.txt")
        self.init_git(); self.commit()
        subprocess.run(["git", "-C", str(self.root), "checkout", "--detach"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = self.work / "detached.md"
        result = self.cli(self.root, "-p", "one.txt", "--encoding", "*:utf-8", "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Branch: detached HEAD", self.text(output))

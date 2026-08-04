import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCRIPT = REPO_ROOT / "bundle.py"

class BundleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.root = self.work / "project"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, relative, content="text\n", binary=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if binary else content.encode("utf-8"))
        return path

    def cli(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(BUNDLE_SCRIPT), *map(str, args)],
            cwd=str(cwd or self.work), text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    @staticmethod
    def text(path):
        return path.read_text(encoding="utf-8")

    @classmethod
    def fields(cls, path, prefix):
        return [line.split(": ", 1)[1] for line in cls.text(path).splitlines()
                if line.startswith(prefix + ": ")]

    @classmethod
    def entries(cls, path):
        result = []
        for line in cls.text(path).splitlines():
            if line.startswith("## `"):
                value = line[4:].split("`", 1)[0].replace("\\", "/")
                if value not in result:
                    result.append(value)
        return result

    @classmethod
    def manifest(cls, path):
        text = cls.text(path)
        if "<!-- bundle:manifest:start -->" not in text:
            return []
        body = text.split("<!-- bundle:manifest:start -->", 1)[1]
        body = body.split("<!-- bundle:manifest:end -->", 1)[0]
        return [line for line in body.splitlines()
                if len(line) > 66 and line[64:66] == "  "]

    def init_git(self, path=None):
        repo = path or self.root
        subprocess.run(["git", "init", str(repo)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        return repo

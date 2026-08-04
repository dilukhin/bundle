"""Общие модели и версия формата bundle."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

__version__ = "0.2.0"
BUNDLE_FORMAT_VERSION = "2"

class BundleError(Exception):
    """Понятная пользователю ошибка формирования bundle."""

@dataclass(frozen=True)
class RepositoryMetadata:
    repository_path: str
    bundle_root: str
    branch: str
    commit: str
    git_status: str
    uncommitted_files: Tuple[str, ...]
    generated_at: str
    git_repository_root: Optional[Path]

    def stable_signature(self):
        return (
            self.repository_path,
            self.branch,
            self.commit,
            self.git_status,
            self.uncommitted_files,
        )


def make_entry_key(kind, display_path):
    prefix = "e" if kind == "external" else "i"
    encoded = quote(display_path.as_posix(), safe="/.~_-")
    return f"{prefix}:{encoded}"

@dataclass(frozen=True)
class SelectedEntry:
    display_path: Path
    source_path: Path
    kind: str
    is_directory: bool
    path_only: bool
    explicit_encoding: Optional[str]
    disable_binary_backup: bool
    repository_path: Optional[str]

    @property
    def key(self):
        return make_entry_key(self.kind, self.display_path)

@dataclass(frozen=True)
class FileSnapshot:
    raw_bytes: bytes
    sha256: str
    entry_type: str
    encoding: str
    text: Optional[str]
    needs_base64: bool

def normalize_encoding_name(encoding):
    if not encoding:
        return "unknown"
    return encoding.lower().replace("_", "-").replace("utf8", "utf-8")


"""Git-метаданные и стабильное чтение исходных байтов."""

import hashlib
import os
import subprocess
from datetime import datetime
from pathlib import Path

from charset_normalizer import from_bytes

from bundle_model import BundleError, FileSnapshot, RepositoryMetadata, normalize_encoding_name
from bundle_paths import _absolute_without_symlink_resolution, _is_within

def _run_git(root, arguments, binary=False):
    try:
        return subprocess.run(
            ["git", "-C", os.fspath(root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
        )
    except FileNotFoundError:
        return None

def _parse_git_status(raw_status):
    if not raw_status:
        return ()
    records = raw_status.split(b"\0")
    items = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2].decode("ascii", errors="replace")
        path = record[3:].decode("utf-8", errors="replace").replace("\\", "/")
        if ("R" in status or "C" in status) and index < len(records):
            original = records[index].decode("utf-8", errors="replace").replace("\\", "/")
            index += 1
            items.append(f"{status} {original} -> {path}")
        else:
            items.append(f"{status} {path}")
    return tuple(sorted(items))

def collect_repository_metadata(root, generated_at=None):
    root_abs = _absolute_without_symlink_resolution(root)
    generated_at = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")

    top_level = _run_git(root_abs, ["rev-parse", "--show-toplevel"])
    if top_level is None or top_level.returncode != 0:
        root_text = root_abs.as_posix()
        return RepositoryMetadata(
            repository_path=root_text,
            bundle_root=root_text,
            branch="not-applicable",
            commit="not-applicable",
            git_status="not-a-git-repository",
            uncommitted_files=(),
            generated_at=generated_at,
            git_repository_root=None,
        )

    repository_root = _absolute_without_symlink_resolution(top_level.stdout.strip())
    commit_result = _run_git(repository_root, ["rev-parse", "HEAD"])
    commit = (
        commit_result.stdout.strip()
        if commit_result is not None and commit_result.returncode == 0
        else "not-applicable"
    )

    branch_result = _run_git(repository_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    branch = (
        branch_result.stdout.strip()
        if branch_result is not None and branch_result.returncode == 0
        else "detached HEAD"
    )

    status_result = _run_git(
        repository_root,
        ["-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        binary=True,
    )
    if status_result is None or status_result.returncode != 0:
        raise BundleError("не удалось получить состояние Git-репозитория")
    uncommitted = _parse_git_status(status_result.stdout)

    return RepositoryMetadata(
        repository_path=repository_root.as_posix(),
        bundle_root=root_abs.as_posix(),
        branch=branch,
        commit=commit,
        git_status="dirty" if uncommitted else "clean",
        uncommitted_files=uncommitted,
        generated_at=generated_at,
        git_repository_root=repository_root,
    )

def repository_relative_path(repository_root, source_path):
    if repository_root is None:
        return None
    source_abs = _absolute_without_symlink_resolution(source_path)
    if not _is_within(repository_root, source_abs):
        return None
    return Path(os.path.relpath(source_abs, repository_root)).as_posix()

def _stat_signature(stat_result):
    return (
        getattr(stat_result, "st_dev", None),
        getattr(stat_result, "st_ino", None),
        stat_result.st_size,
        getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)),
    )

def read_stable_bytes(path):
    try:
        before = os.stat(path)
        with open(path, "rb") as stream:
            descriptor_before = os.fstat(stream.fileno())
            raw_bytes = stream.read()
            descriptor_after = os.fstat(stream.fileno())
        after = os.stat(path)
    except OSError as exc:
        raise BundleError(f"ошибка чтения файла {path}: {exc}") from exc

    signatures = {
        _stat_signature(before),
        _stat_signature(descriptor_before),
        _stat_signature(descriptor_after),
        _stat_signature(after),
    }
    if len(signatures) != 1:
        raise BundleError(f"файл изменился во время формирования bundle: {path}")
    if len(raw_bytes) != before.st_size:
        raise BundleError(f"файл изменился во время формирования bundle: {path}")
    return raw_bytes

def create_file_snapshot(path, explicit_encoding=None, need_sha256=True):
    raw_bytes = read_stable_bytes(path)
    digest = hashlib.sha256(raw_bytes).hexdigest() if need_sha256 else ""

    if b"\x00" in raw_bytes[:4096]:
        return FileSnapshot(raw_bytes, digest, "binary", "binary", None, True)

    encoding = explicit_encoding
    if not encoding:
        result = from_bytes(raw_bytes).best()
        if result is not None:
            encoding = result.encoding
    if not encoding:
        encoding = "utf-8"

    try:
        decoded = raw_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise BundleError(f"не удалось декодировать {path} как {encoding}: {exc}") from exc

    text = decoded.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalize_encoding_name(encoding)
    utf8_family = normalized in {"utf-8", "utf-8-sig", "utf-8-bom"}
    return FileSnapshot(
        raw_bytes=raw_bytes,
        sha256=digest,
        entry_type="text",
        encoding=encoding,
        text=text,
        needs_base64=not utf8_family,
    )


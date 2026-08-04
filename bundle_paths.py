"""Выбор файлов и переносимое представление путей bundle."""

import fnmatch
import os
from pathlib import Path
from urllib.parse import quote

from bundle_model import BundleError

def normalize_pattern(pattern):
    """Нормализовать разделители и маски для одинаковой обработки на разных ОС."""
    pattern = pattern.replace("\\", "/")
    if pattern.endswith(".*"):
        base = pattern[:-2]
        return base + "*" if not base.endswith("*") else base
    if pattern == "*.*":
        return "*"
    return pattern

def has_wildcards(pattern):
    return any(char in pattern for char in "*?[")

def is_exact_path_pattern(pattern):
    pattern = normalize_pattern(pattern)
    if pattern.endswith("/") or has_wildcards(pattern):
        return False
    return (
        pattern.startswith("./")
        or pattern.startswith("../")
        or "/" in pattern
        or Path(pattern).is_absolute()
    )

def match_path_glob(path_str, pattern):
    """Сопоставить POSIX-путь с glob-шаблоном, где ** пересекает каталоги."""
    path_parts = path_str.split("/") if path_str else []
    pattern_parts = pattern.split("/") if pattern else []
    memo = {}

    def match_parts(pattern_index, path_index):
        key = (pattern_index, path_index)
        if key in memo:
            return memo[key]

        if pattern_index == len(pattern_parts):
            result = path_index == len(path_parts)
        elif pattern_parts[pattern_index] == "**":
            result = match_parts(pattern_index + 1, path_index) or (
                path_index < len(path_parts)
                and match_parts(pattern_index, path_index + 1)
            )
        elif path_index == len(path_parts):
            result = False
        else:
            result = fnmatch.fnmatchcase(
                path_parts[path_index], pattern_parts[pattern_index]
            ) and match_parts(pattern_index + 1, path_index + 1)

        memo[key] = result
        return result

    return match_parts(0, 0)

def _absolute_without_symlink_resolution(path):
    """Получить абсолютный путь, не раскрывая символические ссылки."""
    return Path(os.path.abspath(os.fspath(path)))

def _normalized_commonpath(base, candidate):
    try:
        common = os.path.commonpath([os.fspath(base), os.fspath(candidate)])
    except ValueError:
        return None
    return os.path.normcase(common)

def _is_within(base, candidate):
    common = _normalized_commonpath(base, candidate)
    return common is not None and common == os.path.normcase(os.fspath(base))

def make_archive_path(root, source_path):
    """
    Получить переносимый путь записи относительно корня bundle.

    Внутренние файлы получают обычный относительный путь. Внешние файлы сохраняют
    относительный путь с ведущими ``..``. Абсолютный путь ОС в bundle не записывается.
    """
    root_abs = _absolute_without_symlink_resolution(root)
    source_abs = _absolute_without_symlink_resolution(source_path)

    try:
        relative = os.path.relpath(source_abs, root_abs)
    except ValueError as exc:
        raise BundleError(
            "внешний файл нельзя представить относительным путём к корню bundle "
            "(пути находятся на разных дисках или в разных пространствах имён)"
        ) from exc

    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise BundleError(f"не удалось построить относительный путь: {source_path}")
    return relative_path

def entry_kind_for_path(path):
    return "external" if path.parts and path.parts[0] == ".." else "internal"

def make_entry_key(kind, display_path):
    """Построить однозначный ASCII-ключ записи без магических имён каталогов."""
    prefix = "e" if kind == "external" else "i"
    encoded = quote(display_path.as_posix(), safe="/._~-")
    return f"{prefix}:{encoded}"

def resolve_exact_file(root, pattern):
    """Разрешить точный путь в (отображаемый относительный путь, путь чтения, тип)."""
    normalized = normalize_pattern(pattern)
    candidate = Path(normalized)
    source_path = candidate if candidate.is_absolute() else Path(root) / candidate
    source_path = _absolute_without_symlink_resolution(source_path)

    if not source_path.exists() or not source_path.is_file():
        return None

    display_path = make_archive_path(root, source_path)
    return display_path, source_path, entry_kind_for_path(display_path)

def collect_all_paths(root):
    paths = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        rel_dir = dirpath.relative_to(root)
        if rel_dir != Path("."):
            paths.add(rel_dir)
        for name in filenames:
            paths.add(rel_dir / name)
    return paths

def match_pattern(path, pattern, is_dir):
    path_str = path.as_posix()
    pattern = normalize_pattern(pattern)

    if pattern.endswith("/"):
        if not is_dir:
            return False
        dir_pattern = pattern.rstrip("/")
        if not dir_pattern:
            return True
        if has_wildcards(dir_pattern):
            parts = path_str.split("/")
            return any(
                match_path_glob("/".join(parts[:index]), dir_pattern)
                for index in range(1, len(parts) + 1)
            )
        return path_str == dir_pattern or path_str.startswith(dir_pattern + "/")

    if is_dir:
        return False
    if "/" in pattern:
        if has_wildcards(pattern):
            return match_path_glob(path_str, pattern)
        return path_str == pattern
    return fnmatch.fnmatch(path.name, pattern)

def match_entry_pattern(root, display_path, source_path, pattern, is_dir):
    pattern = normalize_pattern(pattern)
    if is_exact_path_pattern(pattern):
        exact = resolve_exact_file(root, pattern)
        return (
            exact is not None
            and exact[0] == display_path
            and _absolute_without_symlink_resolution(exact[1])
            == _absolute_without_symlink_resolution(source_path)
        )
    return match_pattern(display_path, pattern, is_dir)

def parse_key_value_option(option, requires_value=False):
    if not option:
        return []
    items = []
    for part in option.split(","):
        part = part.strip()
        if not part:
            continue
        if requires_value:
            if ":" not in part:
                items.append((normalize_pattern(part), True))
                continue
            pattern, value = part.rsplit(":", 1)
            items.append((normalize_pattern(pattern.strip()), value.strip()))
        else:
            items.append((normalize_pattern(part), True))
    return items


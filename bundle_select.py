"""Формирование канонического набора записей bundle."""

from pathlib import Path
import sys

from bundle_model import BundleError, SelectedEntry
from bundle_paths import (
    _absolute_without_symlink_resolution, collect_all_paths, entry_kind_for_path,
    is_exact_path_pattern, make_entry_key, match_entry_pattern, match_pattern,
    normalize_pattern, parse_key_value_option, resolve_exact_file,
)
from bundle_git import repository_relative_path

def build_selected_entries(root, args, repository_root):
    encoding_rules = []
    for value in args.encoding:
        encoding_rules.extend(parse_key_value_option(value, requires_value=True))
    no_backup_rules = []
    for value in args.no_binary_backup:
        no_backup_rules.extend(parse_key_value_option(value))
    paths_only_rules = []
    for value in args.paths_only:
        paths_only_rules.extend(parse_key_value_option(value))

    all_paths = collect_all_paths(root)
    selected: Dict[Path, Tuple[Path, str, bool]] = {}

    for pattern_group in args.patterns:
        patterns = [
            normalize_pattern(item.strip())
            for item in pattern_group.split(",")
            if item.strip()
        ]
        for pattern in patterns:
            matched = []
            if is_exact_path_pattern(pattern):
                exact = resolve_exact_file(root, pattern)
                if exact is not None:
                    matched.append((exact[0], exact[1], exact[2], False))
            else:
                for relative in sorted(all_paths, key=lambda item: item.as_posix()):
                    source_path = root / relative
                    is_directory = source_path.is_dir()
                    if match_pattern(relative, pattern, is_directory):
                        matched.append((relative, source_path, "internal", is_directory))

            print(f"{pattern} ({len(matched)})", file=sys.stderr)
            if not matched:
                print("  (не найдено)", file=sys.stderr)

            for display_path, source_path, kind, is_directory in matched:
                previous = selected.get(display_path)
                if previous is not None:
                    previous_path = _absolute_without_symlink_resolution(previous[0])
                    current_path = _absolute_without_symlink_resolution(source_path)
                    if previous_path != current_path:
                        raise BundleError(
                            f"конфликт пути bundle {display_path.as_posix()}: "
                            f"{previous_path} и {current_path}"
                        )
                    continue
                selected[display_path] = (source_path, kind, is_directory)

    if args.ignore:
        ignore_patterns = []
        for group in args.ignore:
            ignore_patterns.extend(
                normalize_pattern(item.strip())
                for item in group.split(",")
                if item.strip()
            )
        for display_path in list(selected):
            source_path, _kind, is_directory = selected[display_path]
            if any(
                match_entry_pattern(
                    root, display_path, source_path, pattern, is_directory
                )
                for pattern in ignore_patterns
            ):
                del selected[display_path]

    entries = []
    seen_keys = {}
    for display_path in sorted(selected, key=lambda item: item.as_posix()):
        source_path, kind, is_directory = selected[display_path]
        path_only = False
        if not is_directory:
            path_only = any(
                match_entry_pattern(root, display_path, source_path, pattern, False)
                for pattern, _value in paths_only_rules
            )

        explicit_encoding = None
        if not is_directory and not path_only:
            for pattern, encoding in encoding_rules:
                if match_entry_pattern(root, display_path, source_path, pattern, False):
                    explicit_encoding = encoding
                    break

        disable_backup = False
        if not is_directory and not path_only:
            disable_backup = any(
                match_entry_pattern(root, display_path, source_path, pattern, False)
                for pattern, _value in no_backup_rules
            )

        entry = SelectedEntry(
            display_path=display_path,
            source_path=source_path,
            kind=kind,
            is_directory=is_directory,
            path_only=path_only,
            explicit_encoding=explicit_encoding,
            disable_binary_backup=disable_backup,
            repository_path=repository_relative_path(repository_root, source_path),
        )
        previous_source = seen_keys.get(entry.key)
        if previous_source is not None and previous_source != source_path:
            raise BundleError(f"дублирующийся идентификатор записи: {entry.key}")
        seen_keys[entry.key] = source_path
        entries.append(entry)
    return entries


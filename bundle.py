#!/usr/bin/env python3
"""bundle.py — сборщик исходного кода в Markdown-bundle."""

import argparse
import os
import sys
import tempfile

from bundle_model import BUNDLE_FORMAT_VERSION, BundleError, FileSnapshot, RepositoryMetadata, SelectedEntry, __version__, normalize_encoding_name
from bundle_paths import (
    _absolute_without_symlink_resolution, collect_all_paths, entry_kind_for_path,
    has_wildcards, is_exact_path_pattern, make_archive_path, make_entry_key,
    match_entry_pattern, match_path_glob, match_pattern, normalize_pattern,
    parse_key_value_option, resolve_exact_file,
)
from bundle_git import collect_repository_metadata, create_file_snapshot, read_stable_bytes, repository_relative_path
from bundle_select import build_selected_entries
from bundle_writer import build_fragment, publish_append, publish_stdout, publish_write

class RussianArgumentParser(argparse.ArgumentParser):
    """Минимальная русификация стандартного вывода argparse."""

    def format_usage(self):
        return super().format_usage().replace("usage:", "Использование:", 1)

    def format_help(self):
        return super().format_help().replace("usage:", "Использование:", 1)

    def error(self, message):
        replacements = {
            "unrecognized arguments:": "неизвестные аргументы:",
            "expected one argument": "требуется один аргумент",
            "not allowed with argument": "нельзя использовать вместе с аргументом",
            "invalid choice:": "недопустимое значение:",
        }
        for source, target in replacements.items():
            message = message.replace(source, target)
        self.print_usage(sys.stderr)
        self.exit(2, f"Ошибка: {message}\n")

def show_short_help():
    print(f"""
bundle.py {__version__} — сборщик исходного кода в Markdown-bundle
Использование:
  python bundle.py ROOT -p "*.cpp,*.h" -o bundle.md
  python bundle.py ROOT -p "src/" -a archive.md
Полная справка: python bundle.py --help
""")
    sys.exit(0)

def expand_patterns_file(argv):
    """Заменить --patterns-file на последовательность -p с сохранением порядка."""
    new_argv = []
    i = 0
    while i < len(argv):
        if argv[i] != "--patterns-file":
            new_argv.append(argv[i])
            i += 1
            continue

        if i + 1 >= len(argv):
            print("Ошибка: --patterns-file требует аргумент", file=sys.stderr)
            sys.exit(1)

        filepath = argv[i + 1]
        if not os.path.exists(filepath):
            print(f"Ошибка: файл шаблонов не найден: {filepath}", file=sys.stderr)
            sys.exit(1)

        try:
            with open(filepath, "r", encoding="utf-8-sig") as stream:
                lines = stream.readlines()
        except UnicodeDecodeError:
            try:
                with open(filepath, "r", encoding="windows-1251") as stream:
                    lines = stream.readlines()
            except UnicodeDecodeError:
                print(
                    f"Ошибка: не удалось прочитать файл шаблонов как UTF-8 или Windows-1251: {filepath}",
                    file=sys.stderr,
                )
                sys.exit(1)

        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                new_argv.extend(("-p", normalize_pattern(line)))
        i += 2
    return new_argv

def create_argument_parser():
    parser = RussianArgumentParser(
        description=f"bundle.py {__version__} — сборщик исходного кода в Markdown-bundle",
        epilog='Пример: python bundle.py . -p "*.cpp,tools/" --ignore "test/" -o bundle.md',
        add_help=False,
    )
    parser._positionals.title = "Позиционные аргументы"
    parser._optionals.title = "Параметры"
    parser.add_argument("-h", "--help", action="help", help="Показать подробную справку и выйти")
    parser.add_argument("root", nargs="?", default=".", help="Корневая директория проекта")
    parser.add_argument(
        "-p", "--patterns", action="append", default=[],
        help="Добавить файлы и директории по шаблонам; опцию можно повторять",
    )
    parser.add_argument(
        "--ignore", action="append", default=[],
        help="Исключить файлы и директории по шаблонам",
    )
    parser.add_argument(
        "--paths-only", action="append", default=[],
        help="Добавить только путь без содержимого; такие записи не входят в manifest",
    )
    parser.add_argument(
        "--encoding", action="append", default=[],
        help="Задать кодировку в виде шаблон:кодировка",
    )
    parser.add_argument(
        "--no-binary-backup", action="append", default=[],
        help="Не сохранять Base64 исходных байтов для выбранного текстового файла",
    )
    parser.add_argument(
        "--no-metadata", action="store_true",
        help="Не добавлять расширенный блок метаданных фрагмента",
    )
    parser.add_argument(
        "--no-manifest", action="store_true",
        help="Не добавлять SHA-256 manifest фрагмента",
    )
    parser.add_argument("--version", action="version", version=f"bundle.py {__version__}")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", help="Записать bundle с заменой файла")
    output_group.add_argument("-a", "--append", help="Добавить самостоятельный фрагмент")
    return parser

def main():
    if len(sys.argv) == 1:
        show_short_help()

    args = create_argument_parser().parse_args()
    root = _absolute_without_symlink_resolution(args.root)
    if not root.exists() or not root.is_dir():
        print(f"Ошибка: корневая директория не существует: {root}", file=sys.stderr)
        return 1

    fragment_path = None
    try:
        metadata_before = collect_repository_metadata(root)
        entries = build_selected_entries(root, args, metadata_before.git_repository_root)
        if not entries:
            print("Предупреждение: создан пустой bundle", file=sys.stderr)

        temp_handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".bundle.md"
        )
        fragment_path = temp_handle.name
        temp_handle.close()

        included_count, counts = build_fragment(
            fragment_path,
            entries,
            metadata_before,
            include_metadata=not args.no_metadata,
            include_manifest=not args.no_manifest,
        )

        if not args.no_metadata and metadata_before.git_repository_root is not None:
            metadata_after = collect_repository_metadata(
                root, generated_at=metadata_before.generated_at
            )
            if metadata_before.stable_signature() != metadata_after.stable_signature():
                raise BundleError(
                    "состояние Git-репозитория изменилось во время формирования bundle"
                )

        if args.output:
            publish_write(fragment_path, args.output)
            destination = args.output
        elif args.append:
            publish_append(fragment_path, args.append)
            destination = args.append
        else:
            publish_stdout(fragment_path)
            destination = "stdout"

        print(f"bundle.py {__version__}: записано {destination}", file=sys.stderr)
        print(f"Всего файлов: {included_count}", file=sys.stderr)
        print(f"UTF-8: {counts['utf8']}", file=sys.stderr)
        print(f"Конвертировано: {counts['converted']}", file=sys.stderr)
        print(f"Бинарные: {counts['binary']}", file=sys.stderr)
        print(f"Только пути: {counts['path_only']}", file=sys.stderr)
        return 0
    except BundleError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Ошибка ввода-вывода: {exc}", file=sys.stderr)
        return 1
    finally:
        if fragment_path:
            try:
                os.unlink(fragment_path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.argv = expand_patterns_file(sys.argv)
    sys.exit(main())

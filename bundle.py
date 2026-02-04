#!/usr/bin/env python3
"""
bundle.py — Сборщик исходного кода в единый Markdown-бандл
==========================================================

Назначение:
Собирает файлы проекта в один читаемый документ с автоматической обработкой кодировок,
сохраняя оригинальные байты при необходимости. Поддерживает гибкую фильтрацию по шаблонам.

Формат шаблонов:
  • Шаблон с завершающим '/' → только директории (рекурсивно)
    Пример: "tools/", "src/legacy/"
  • Шаблон без '/' → только файлы
    Пример: "*.cpp", "CMakeLists.txt"

Опции обрабатываются слева направо. Каждая опция применяется только к набору путей,
сформированному предыдущими опциями.

Автор: Дмитрий Илюхин (d.ilyhin)
"""

import argparse
import os
import sys
import base64
import fnmatch
from pathlib import Path
from charset_normalizer import from_path


def show_short_help():
    print("""
bundle.py — сборщик исходного кода в Markdown-бандл

Быстрый старт:
  python bundle.py . -p "*.cpp,*.h" -o bundle.md

Ключевые опции:
  -p "*.cpp,tools/"      — добавить файлы и/или директории
  --ignore "test/"       — исключить пути (файлы/директории)
  --paths-only "*.log"   — добавить только пути, без содержимого
  --encoding "tools/:cp866" — задать кодировку для шаблона
  --no-binary-backup "*.tmp" — отключить base64 для шаблона

Вывод:
  -o file.md             — записать в файл (перезапись)
  -a file.md             — добавить в файл
  (без -o/-a)            — вывод в stdout

Полная справка: python bundle.py --help
""")
    sys.exit(0)


def is_binary_file(path, sample_size=1024):
    try:
        with open(path, 'rb') as f:
            sample = f.read(sample_size)
            if b'\x00' in sample:
                return True
            return False
    except Exception:
        return True


def normalize_encoding_name(enc):
    if not enc:
        return "unknown"
    return enc.lower().replace('_', '-').replace('utf8', 'utf-8')


def read_file_with_encoding(path, explicit_encoding=None):
    if is_binary_ofile(path):
        return None, "binary", True, True, None

    try:
        with open(path, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        return None, None, False, False, f"Ошибка чтения: {e}"

    encoding = explicit_encoding
    if not encoding:
        results = from_path(path).best()
        if results:
            encoding = results.encoding

    if not encoding:
        encoding = "utf-8"

    try:
        text_with_original_line_endings = raw_bytes.decode(encoding)
        normalized_text = text_with_original_line_endings.replace('\r\n', '\n').replace('\r', '\n')
        normalized_enc = normalize_encoding_name(encoding)
        is_utf8_family = normalized_enc in ['utf-8', 'utf-8-sig', 'utf-8-bom', 'utf8', 'utf8-sig']
        needs_base64 = not is_utf8_family
        return normalized_text, encoding, needs_base64, False, None
    except (UnicodeDecodeError, LookupError) as e:
        return None, encoding, True, True, f"Декодирование {encoding} не удалось: {e}"


def is_binary_ofile(path):
    """Alias for is_binary_file to avoid confusion in main logic"""
    return is_binary_file(path)


def collect_all_paths(root):
    """Собрать все файлы и директории рекурсивно"""
    paths = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        rel_dir = dirpath.relative_to(root)
        if rel_dir != Path("."):
            paths.add(rel_dir)
        for name in filenames:
            rel_file = rel_dir / name
            paths.add(rel_file)
    return paths


def match_pattern(path, pattern, is_dir):
    """
    Сопоставить путь с шаблоном.
    pattern: строка, возможно с завершающим '/'
    is_dir: является ли path директорией
    """
    if pattern.endswith('/'):
        # Шаблон для директорий
        if not is_dir:
            return False
        dir_pattern = pattern.rstrip('/')
        if dir_pattern == "":
            return True  # шаблон "/" совпадает с корнем
        # Совпадение: путь == шаблон ИЛИ путь внутри шаблона
        return str(path) == dir_pattern or str(path).startswith(dir_pattern + '/')
    else:
        # Шаблон для файлов
        if is_dir:
            return False
        # Совпадение только по имени файла
        return fnmatch.fnmatch(path.name, pattern)


def apply_patterns_to_set(current_set, root, patterns_str, action="include"):
    """
    Применить список шаблонов к текущему набору путей.
    patterns_str: строка вида "pattern1,pattern2"
    action: "include" или "exclude"
    """
    if not patterns_str:
        return current_set

    patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]
    all_paths = None
    new_set = set()

    if action == "include":
        # Для включения — собираем все пути из root один раз
        all_paths = collect_all_paths(root)

    for item in current_set if action == "exclude" else (all_paths or set()):
        rel_path = item if isinstance(item, Path) else Path(item)
        is_dir = (root / rel_path).is_dir()

        matched = False
        for pat in patterns:
            if match_pattern(rel_path, pat, is_dir):
                matched = True
                break

        if action == "include" and matched:
            new_set.add(rel_path)
        elif action == "exclude" and not matched:
            new_set.add(rel_path)

    return new_set if action == "exclude" else (current_set | new_set)


def parse_key_value_option(opt_str):
    """Разобрать опцию вида 'pattern: value' или 'pattern' (для флагов)"""
    if not opt_str:
        return []
    items = []
    for part in opt_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            pat, val = part.split(":", 1)
            items.append((pat.strip(), val.strip()))
        else:
            items.append((part, True))  # для флагов вроде --no-binary-backup
    return items


def main():
    if len(sys.argv) == 1:
        show_short_help()

    ap = argparse.ArgumentParser(
        description="Сборщик исходного кода в единый Markdown-бандл",
        epilog="Пример: python bundle.py . -p \"*.cpp,tools/\" --ignore \"test/\" -o bundle.md"
    )
    ap.add_argument("root", nargs="?", default=".", help="Корневая директория проекта")
    ap.add_argument("-p", "--patterns", action="append", default=[],
                    help="Добавить файлы/директории по шаблонам (можно указывать несколько раз)")
    ap.add_argument("--ignore", action="append", default=[],
                    help="Исключить файлы/директории по шаблонам (можно указывать несколько раз)")
    ap.add_argument("--paths-only", action="append", default=[],
                    help="Добавить только пути (без содержимого) по шаблонам")
    ap.add_argument("--encoding", action="append", default=[],
                    help="Задать кодировку: 'шаблон:кодировка' (можно несколько раз)")
    ap.add_argument("--no-binary-backup", action="append", default=[],
                    help="Отключить base64 для шаблона (можно несколько раз)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("-o", "--output", help="Записать в файл (перезапись)")
    group.add_argument("-a", "--append", help="Добавить в файл")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"❌ Ошибка: путь не существует: {root}", file=sys.stderr)
        return 1

    # Начинаем с пустого набора
    current_set = set()

    # Парсим правила для encoding и no-binary-backup
    encoding_rules = []
    for enc_opt in args.encoding:
        encoding_rules.extend(parse_key_value_option(enc_opt))

    no_backup_rules = []
    for nb_opt in args.no_binary_backup:
        no_backup_rules.extend(parse_key_value_option(nb_opt))

    paths_only_rules = []
    for po_opt in args.paths_only:
        paths_only_rules.extend(parse_key_value_option(po_opt))

    # Обрабатываем опции слева направо
    all_args = []
    for pat in args.patterns:
        all_args.append(('include', pat))
    for ign in args.ignore:
        all_args.append(('exclude', ign))

    for action, pattern_str in all_args:
        current_set = apply_patterns_to_set(current_set, root, pattern_str, action)

    if not current_set:
        print("⚠️  Не найдено файлов по указанным шаблонам", file=sys.stderr)
        return 1

    # Преобразуем в отсортированный список
    sorted_paths = sorted(current_set)

    # Определяем, куда писать
    output_mode = 'stdout'
    output_path = None
    if args.output:
        output_mode = 'write'
        output_path = args.output
    elif args.append:
        output_mode = 'append'
        output_path = args.append

    # Открываем поток вывода
    if output_mode == 'stdout':
        out_stream = sys.stdout
        # Для stdout не используем контекстный менеджер
        # Пишем напрямую с нужными параметрами
        class StdoutWrapper:
            def write(self, s):
                sys.stdout.write(s)
            def flush(self):
                sys.stdout.flush()
        out = StdoutWrapper()
        # Устанавливаем newline='\n' через reconfigure (Python 3.7+)
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(newline='\n')
    else:
        mode = 'w' if output_mode == 'write' else 'a'
        out_file = open(output_path, mode, encoding='utf-8', newline='\n')
        out = out_file

    try:
        if output_mode != 'stdout':
            # Заголовок только при записи в файл
            out.write(f"# Bundle from `{root}`\n\n")
            # Проверяем, есть ли хотя бы одно правило --no-binary-backup
            has_no_backup = any(nb_rule[1] is True for nb_rule in no_backup_rules)
            if has_no_backup:
                out.write("<!-- bundle:no-binary-backup=true -->\n\n")

        # Счётчики
        total_count = 0
        utf8_count = 0
        converted_count = 0
        binary_count = 0
        paths_only_count = 0

        for rel in sorted_paths:
            full_path = root / rel
            is_dir = full_path.is_dir()

            # Проверяем, попадает ли под --paths-only
            is_paths_only = False
            for pat, _ in paths_only_rules:
                if match_pattern(rel, pat, is_dir):
                    is_paths_only = True
                    break

            if is_dir:
                # Директории просто перечисляем, если не paths-only (но они и так без содержимого)
                out.write("---\n")
                out.write(f"## `{rel}/`\n")
                out.write("```\n")
                out.write("# directory\n")
                out.write("```\n\n")
                total_count += 1
                continue

            # Для файлов определяем явную кодировку
            explicit_encoding = None
            for pat, enc in encoding_rules:
                if match_pattern(rel, pat, False):  # файлы
                    explicit_encoding = enc
                    break

            # Проверяем, отключён ли base64
            disable_base64 = False
            for pat, _ in no_backup_rules:
                if match_pattern(rel, pat, False):
                    disable_base64 = True
                    break

            if is_paths_only:
                out.write("---\n")
                out.write(f"## `{rel}`\n")
                out.write("```\n")
                out.write("# path only\n")
                out.write("```\n\n")
                paths_only_count += 1
                total_count += 1
                continue

            # Читаем файл
            text, detected_enc, needs_base64, is_binary, error = read_file_with_encoding(
                full_path, explicit_encoding
            )

            out.write("---\n")
            out.write(f"## `{rel}`\n")

            if error:
                out.write(f"<!-- bundle:error={error} -->\n")
                out.write("```text\n")
                out.write(f"<<ОШИБКА: {error}>>\n")
                out.write("```\n\n")
                print(f"[ERR] {rel}: {error}", file=sys.stderr)
                total_count += 1
                continue

            if is_binary:
                binary_count += 1
                total_count += 1
                norm_enc = normalize_encoding_name(detected_enc)
                out.write(f"<!-- bundle:binary=true encoding={norm_enc} -->\n")
                out.write(f"## `{rel}` (binary)\n")
                out.write("```base64\n")
                with open(full_path, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n\n")
                print(f"[BIN] {rel} ({norm_enc})", file=sys.stderr)
                continue

            # Текстовый файл
            norm_enc = normalize_encoding_name(detected_enc)
            out.write(f"<!-- bundle:encoding={norm_enc} -->\n")
            lang = rel.suffix[1:] if rel.suffix else ""
            out.write(f"```{lang}\n")
            if text and not text.endswith('\n'):
                text += '\n'
            out.write(text)
            out.write("```\n")

            # Base64 только если нужно И не отключено
            if needs_base64 and not disable_base64:
                converted_count += 1
                total_count += 1
                out.write(f"\n## `{rel}` (original bytes)\n")
                out.write("```base64\n")
                with open(full_path, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n\n")
                print(f"[CONV] {rel} ({norm_enc} → UTF-8 + base64)", file=sys.stderr)
            else:
                if needs_base64:
                    converted_count += 1
                    print(f"[CONV] {rel} ({norm_enc} → UTF-8, base64 skipped)", file=sys.stderr)
                else:
                    utf8_count += 1
                    print(f"[UTF8] {rel} ({norm_enc})", file=sys.stderr)
                total_count += 1

            out.write("\n")

        # Вывод статистики только в stderr
        if output_mode != 'stdout':
            print(f"\n✅ Записано {output_path}", file=sys.stderr)
        print(f"   Всего файлов: {total_count}", file=sys.stderr)
        print(f"   • UTF-8 (без дублирования): {utf8_count}", file=sys.stderr)
        print(f"   • Конвертировано: {converted_count}", file=sys.stderr)
        print(f"   • Бинарные: {binary_count}", file=sys.stderr)
        print(f"   • Только пути: {paths_only_count}", file=sys.stderr)
        if any(nb_rule[1] is True for nb_rule in no_backup_rules):
            print(f"\n⚠️  Внимание: base64 отключён для некоторых файлов", file=sys.stderr)

    finally:
        if output_mode != 'stdout':
            out_file.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
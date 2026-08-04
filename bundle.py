#!/usr/bin/env python3
"""
bundle.py — Сборщик исходного кода в единый Markdown-бандл
==========================================================
Назначение:
Собирает файлы проекта в один читаемый документ с автоматической обработкой кодировок,
сохраняя оригинальные байты при необходимости. Поддерживает гибкую фильтрацию по шаблонам.
Автор: Дмитрий Илюхин (dilukhin@hotmail.com)
"""

import argparse
import os
import sys
import base64
import fnmatch
from pathlib import Path
from charset_normalizer import from_path


__version__ = "0.1.0"


def show_short_help():
    print(f"""
bundle.py {__version__} — сборщик исходного кода в Markdown-бандл
Быстрый старт:
  python bundle.py . -p "*.cpp,*.h" -o bundle.md
Ключевые опции:
  -p "*.cpp,tools/"           — добавить файлы/директории (через запятую или несколько раз)
  --patterns-file <file>      — загрузить шаблоны из файла (по одному на строку, # — комментарий)
  --ignore "test/"            — исключить пути из текущего набора
  --paths-only "*.log"        — добавить только пути, без содержимого
  --encoding "tools/:cp866"   — принудительно задать кодировку (напр. "*.bat:cp866")
  --no-binary-backupp "*.tmp" — отключить base64-дубли для шаблона
  --version                   — вывести версию утилиты
Вывод:
  -o bundle.md                — записать в файл (перезапись)
  -a archive.md               — добавить в файл
  (без -o/-a)                 — вывод в stdout
Полная справка: python bundle.py --help
""")
    sys.exit(0)


def expand_patterns_file(argv):
    """Заменяет --patterns-file на список -p аргументов для сохранения порядка."""
    new_argv = []
    i = 0
    while i < len(argv):
        if argv[i] == '--patterns-file':
            if i + 1 >= len(argv):
                print("Error: --patterns-file требует аргумент", file=sys.stderr)
                sys.exit(1)
            filepath = argv[i + 1]
            if not os.path.exists(filepath):
                print(f"Error: Файл шаблонов не найден: {filepath}", file=sys.stderr)
                sys.exit(1)

            lines = []
            # Попытка чтения UTF-8 (с автоматическим удалением BOM, если есть)
            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                # Фоллбэк на Windows-1251 для кириллических конфигов
                try:
                    with open(filepath, 'r', encoding='windows-1251') as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    print(f"Error: Не удалось прочитать файл (не UTF-8/cp1251): {filepath}", file=sys.stderr)
                    sys.exit(1)

            for line in lines:
                line = line.strip()
                # Пропускаем пустые строки и комментарии
                if line and not line.startswith('#'):
                    new_argv.append('-p')
                    new_argv.append(normalize_pattern(line))
            i += 2
        else:
            new_argv.append(argv[i])
            i += 1
    return new_argv


def is_binary_file(path, sample_size=4096):
    try:
        with open(path, 'rb') as f:
            sample = f.read(sample_size)
            if b'\x00' in sample:
                return True
            return False
    except Exception:
        return True


def normalize_pattern(pat):
    """Нормализует разделители и маски для одинаковой обработки на разных ОС."""
    pat = pat.replace('\\', '/')
    if pat.endswith('.*'):
        base = pat[:-2]
        # Если в базе уже есть *, fnmatch сам поймает расширения.
        # Если нет *, добавляем *, чтобы поймать и файлы без расширений
        return base + '*' if not base.endswith('*') else base
    if pat == '*.*':
        return '*'
    return pat


def has_wildcards(pattern):
    """Проверить наличие glob-метасимволов в шаблоне."""
    return any(char in pattern for char in '*?[')


def is_exact_path_pattern(pattern):
    """Отличить точный путь от glob-маски и селектора каталога."""
    pattern = normalize_pattern(pattern)
    if pattern.endswith('/') or has_wildcards(pattern):
        return False
    return (
        pattern.startswith('./')
        or pattern.startswith('../')
        or '/' in pattern
        or Path(pattern).is_absolute()
    )


def match_path_glob(path_str, pattern):
    """Сопоставить POSIX-путь с glob-шаблоном, где ** пересекает каталоги."""
    path_parts = path_str.split('/') if path_str else []
    pattern_parts = pattern.split('/') if pattern else []
    memo = {}

    def match_parts(pattern_index, path_index):
        key = (pattern_index, path_index)
        if key in memo:
            return memo[key]

        if pattern_index == len(pattern_parts):
            result = path_index == len(path_parts)
        elif pattern_parts[pattern_index] == '**':
            result = (
                match_parts(pattern_index + 1, path_index)
                or (
                    path_index < len(path_parts)
                    and match_parts(pattern_index, path_index + 1)
                )
            )
        elif path_index == len(path_parts):
            result = False
        else:
            result = (
                fnmatch.fnmatchcase(path_parts[path_index], pattern_parts[pattern_index])
                and match_parts(pattern_index + 1, path_index + 1)
            )

        memo[key] = result
        return result

    return match_parts(0, 0)


def _absolute_without_symlink_resolution(path):
    """Получить нормализованный абсолютный путь, не раскрывая символические ссылки."""
    return Path(os.path.abspath(os.fspath(path)))


def _safe_external_part(part):
    if part == '..':
        return '__parent__'
    if part in ('', '.'):
        return None
    return part.replace(':', '')


def make_archive_path(root, source_path):
    """Построить безопасный путь записи bundle для внутреннего или внешнего файла."""
    root_abs = _absolute_without_symlink_resolution(root)
    source_abs = _absolute_without_symlink_resolution(source_path)

    try:
        common = os.path.commonpath([os.fspath(root_abs), os.fspath(source_abs)])
    except ValueError:
        common = None

    if common is not None and os.path.normcase(common) == os.path.normcase(os.fspath(root_abs)):
        return Path(os.path.relpath(source_abs, root_abs))

    try:
        relative = Path(os.path.relpath(source_abs, root_abs))
        safe_parts = [
            safe
            for safe in (_safe_external_part(part) for part in relative.parts)
            if safe is not None
        ]
    except ValueError:
        drive = source_abs.drive.rstrip(':\\/') or 'root'
        safe_parts = [drive]
        anchor = source_abs.anchor
        for part in source_abs.parts:
            if part == anchor:
                continue
            safe = _safe_external_part(part)
            if safe is not None:
                safe_parts.append(safe)

    return Path('__external__', *safe_parts)


def resolve_exact_file(root, pattern):
    """Разрешить точный путь в пару (путь в bundle, путь чтения)."""
    normalized = normalize_pattern(pattern)
    candidate = Path(normalized)
    source_path = candidate if candidate.is_absolute() else Path(root) / candidate
    source_path = _absolute_without_symlink_resolution(source_path)

    if not source_path.exists() or not source_path.is_file():
        return None

    return make_archive_path(root, source_path), source_path


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
    path_str = str(path).replace('\\', '/')
    pattern = normalize_pattern(pattern)

    if pattern.endswith('/'):
        # Шаблон для директорий. Сохраняем существующую семантику:
        # выбираются сами каталоги, но не файлы внутри них.
        if not is_dir:
            return False
        dir_pattern = pattern.rstrip('/')
        if dir_pattern == "":
            return True  # шаблон "/" совпадает с корнем
        if has_wildcards(dir_pattern):
            parts = path_str.split('/')
            return any(
                match_path_glob('/'.join(parts[:index]), dir_pattern)
                for index in range(1, len(parts) + 1)
            )
        # Совпадение: путь == шаблон ИЛИ путь внутри шаблона
        return path_str == dir_pattern or path_str.startswith(dir_pattern + '/')

    # Шаблон для файлов
    if is_dir:
        return False
    if '/' in pattern:
        # Путь с glob-метасимволами раскрывается посегментно.
        if has_wildcards(pattern):
            return match_path_glob(path_str, pattern)
        # Путь без glob-метасимволов остаётся точным путём.
        return path_str == pattern
    # Шаблон без разделителя ищет по имени файла во всём дереве.
    return fnmatch.fnmatch(path.name, pattern)


def match_entry_pattern(root, archive_path, source_path, pattern, is_dir):
    """Применить правило к записи, включая точные внешние пути."""
    pattern = normalize_pattern(pattern)
    if is_exact_path_pattern(pattern):
        exact = resolve_exact_file(root, pattern)
        return exact is not None and exact[0] == archive_path
    return match_pattern(archive_path, pattern, is_dir)


def parse_key_value_option(opt_str, requires_value=False):
    """Разобрать список шаблонов или правил вида 'pattern:value'."""
    if not opt_str:
        return []
    items = []
    for part in opt_str.split(","):
        part = part.strip()
        if not part:
            continue
        if requires_value:
            if ":" not in part:
                items.append((normalize_pattern(part), True))
                continue
            pat, val = part.rsplit(":", 1)
            items.append((normalize_pattern(pat.strip()), val.strip()))
        else:
            items.append((normalize_pattern(part), True))
    return items


def write_bundle_header(out, root):
    """Записать метаданные нового или добавляемого фрагмента bundle."""
    out.write(f"<!-- bundle:version={__version__} -->\n")
    out.write(f"# Bundle {__version__} from `{root}`\n")


def main():
    if len(sys.argv) == 1:
        show_short_help()
    ap = argparse.ArgumentParser(
        description=f"bundle.py {__version__} — сборщик исходного кода в единый Markdown-бандл",
        epilog="Пример: python bundle.py . -p \"*.cpp,tools/\" --ignore \"test/\" -o bundle.md"
    )
    ap.add_argument("root", nargs="?", default=".", help="Корневая директория проекта")
    ap.add_argument("-p", "--patterns", action="append", default=[],
                    help="Добавить файлы/директории по шаблонам (можно указывать несколько раз)")
    ap.add_argument("--ignore", action="append", default=[],
                    help="Исключить файлы/директории по шаблонам (можно несколько раз)")
    ap.add_argument("--paths-only", action="append", default=[],
                    help="Добавить только пути (без содержимого) по шаблонам")
    ap.add_argument("--encoding", action="append", default=[],
                    help="Задать кодировку: 'шаблон:кодировка' (можно несколько раз)")
    ap.add_argument("--no-binary-backup", action="append", default=[],
                    help="Отключить base64 для шаблона (можно несколько раз)")
    ap.add_argument("--version", action="version", version=f"bundle.py {__version__}")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("-o", "--output", help="Записать в файл (перезапись)")
    group.add_argument("-a", "--append", help="Добавить в файл")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"❌ Ошибка: путь не существует: {root}", file=sys.stderr)
        return 1

    # Подготовка правил
    encoding_rules = []
    for enc_opt in args.encoding:
        encoding_rules.extend(parse_key_value_option(enc_opt, requires_value=True))
    no_backup_rules = []
    for nb_opt in args.no_binary_backup:
        no_backup_rules.extend(parse_key_value_option(nb_opt))
    paths_only_rules = []
    for po_opt in args.paths_only:
        paths_only_rules.extend(parse_key_value_option(po_opt))

    all_paths = collect_all_paths(root)
    current_set = set()
    source_paths = {}
    file_cache = {}  # archive_path -> {type, text, enc, is_bin, needs_b64, error}
    RED = "\033[91m"
    RESET = "\033[0m"

    # 1. Обработка паттернов включения с групповым выводом
    for pattern_str in args.patterns:
        sub_patterns = [normalize_pattern(p.strip()) for p in pattern_str.split(",") if p.strip()]
        for pat in sub_patterns:
            matched = []
            if is_exact_path_pattern(pat):
                exact = resolve_exact_file(root, pat)
                if exact is not None:
                    matched.append(exact)
            else:
                for p in sorted(all_paths, key=lambda item: item.as_posix()):
                    source_path = root / p
                    is_dir = source_path.is_dir()
                    if match_pattern(p, pat, is_dir):
                        matched.append((p, source_path))

            print(f"{pat} ({len(matched)})", file=sys.stderr)
            if not matched:
                print(f"  {RED}(не найдено){RESET}", file=sys.stderr)
                continue

            for p, source_path in matched:
                previous_source = source_paths.get(p)
                if previous_source is not None and _absolute_without_symlink_resolution(previous_source) != _absolute_without_symlink_resolution(source_path):
                    print(f"  [ERR] конфликт пути bundle: {p}", file=sys.stderr)
                    continue

                current_set.add(p)
                source_paths[p] = source_path
                is_dir = source_path.is_dir()
                is_po = any(
                    match_entry_pattern(root, p, source_path, po, is_dir)
                    for po, _ in paths_only_rules
                )

                if is_po:
                    file_cache[p] = {"type": "path_only", "text": None, "enc": None, "is_bin": False, "needs_b64": False, "error": None}
                    print(f"  [PATH] {p}", file=sys.stderr)
                    continue

                expl_enc = None
                for ep, encoding in encoding_rules:
                    if match_entry_pattern(root, p, source_path, ep, False):
                        expl_enc = encoding
                        break
                disable_b64 = any(
                    match_entry_pattern(root, p, source_path, nb, False)
                    for nb, _ in no_backup_rules
                )

                text, det_enc, needs_b64, is_bin, err = read_file_with_encoding(source_path, expl_enc)
                norm_enc = normalize_encoding_name(det_enc)

                if err:
                    file_cache[p] = {"type": "error", "text": None, "enc": det_enc, "is_bin": False, "needs_b64": False, "error": err}
                    print(f"  [ERR] {p} ({err})", file=sys.stderr)
                elif is_bin:
                    file_cache[p] = {"type": "binary", "text": text, "enc": det_enc, "is_bin": True, "needs_b64": True, "error": None}
                    print(f"  [BIN] {p} ({norm_enc})", file=sys.stderr)
                elif norm_enc == "utf-8":
                    file_cache[p] = {"type": "utf8", "text": text, "enc": det_enc, "is_bin": False, "needs_b64": False, "error": None}
                    print(f"  [UTF8] {p} ({norm_enc})", file=sys.stderr)
                else:
                    nb = needs_b64 and not disable_b64
                    file_cache[p] = {"type": "converted", "text": text, "enc": det_enc, "is_bin": False, "needs_b64": nb, "error": None}
                    print(f"  [CONV] {p} ({norm_enc})", file=sys.stderr)

    # 2. Обработка исключений
    if args.ignore:
        for ign_str in args.ignore:
            ign_pats = [normalize_pattern(p.strip()) for p in ign_str.split(",") if p.strip()]
            for p in list(current_set):
                source_path = source_paths[p]
                is_dir = source_path.is_dir()
                if any(match_entry_pattern(root, p, source_path, ign, is_dir) for ign in ign_pats):
                    current_set.remove(p)
                    source_paths.pop(p, None)
                    file_cache.pop(p, None)

    if not current_set:
        print("⚠️  Не найдено файлов по указанным шаблонам", file=sys.stderr)
        return 1

    # 3. Настройка вывода
    output_mode = 'stdout'
    output_path = None
    if args.output:
        output_mode = 'write'
        output_path = args.output
    elif args.append:
        output_mode = 'append'
        output_path = args.append

    if output_mode == 'stdout':
        out = sys.stdout
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(newline='\n')
    else:
        mode = 'w' if output_mode == 'write' else 'a'
        out = open(output_path, mode, encoding='utf-8', newline='\n')

    try:
        write_bundle_header(out, root)

        sorted_paths = sorted(current_set)
        # Счётчики для финальной статистики
        utf8_count = converted_count = binary_count = paths_only_count = 0

        for rel in sorted_paths:
            source_path = source_paths[rel]
            is_dir = source_path.is_dir()
            if is_dir:
                out.write("---\n")
                out.write(f"## `{rel}/`\n")
                out.write("```\n")
                out.write("# directory\n")
                out.write("```\n")
                continue

            info = file_cache.get(rel)
            if not info:
                continue

            out.write("---\n")
            out.write(f"## `{rel}`\n")

            if info["type"] == "path_only":
                out.write("```\n")
                out.write("# path only\n")
                out.write("```\n")
                paths_only_count += 1
                continue

            if info["type"] == "error":
                out.write(f"<!-- bundle:error={info['error']} -->\n")
                out.write("```text\n")
                out.write(f"<<ОШИБКА: {info['error']}>>\n")
                out.write("```\n")
                continue

            if info["type"] == "binary":
                norm_enc = normalize_encoding_name(info["enc"])
                out.write(f"<!-- bundle:binary=true encoding={norm_enc} -->\n")
                out.write(f"## `{rel}` (binary)\n")
                out.write("```base64\n")
                with open(source_path, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n")
                binary_count += 1
                continue

            # Текстовый файл
            text = info["text"]
            norm_enc = normalize_encoding_name(info["enc"])
            lang = rel.suffix[1:] if rel.suffix else ""
            out.write(f"<!-- bundle:encoding={norm_enc} -->\n")
            out.write(f"```{lang}\n")
            if text and not text.endswith('\n'):
                text += '\n'
            out.write(text)
            out.write("```\n")

            if info["needs_b64"]:
                out.write(f"\n## `{rel}` (original bytes)\n")
                out.write("```base64\n")
                with open(source_path, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n")
                converted_count += 1
            else:
                utf8_count += 1

        out.write("\n")
        # Финальная статистика
        print(f"\n✅ bundle.py {__version__}: записано {output_path if output_path else 'stdout'}", file=sys.stderr)
        print(f"   Всего файлов: {utf8_count + converted_count + binary_count + paths_only_count}", file=sys.stderr)
        print(f"   • UTF-8 (без дублирования): {utf8_count}", file=sys.stderr)
        print(f"   • Конвертировано: {converted_count}", file=sys.stderr)
        print(f"   • Бинарные: {binary_count}", file=sys.stderr)
        print(f"   • Только пути: {paths_only_count}", file=sys.stderr)
        if any(nb_rule[1] is True for nb_rule in no_backup_rules):
            print(f"\n⚠️  Внимание: base64 отключён для некоторых файлов", file=sys.stderr)

    finally:
        if output_mode != 'stdout':
            out.close()
    return 0


if __name__ == "__main__":
    sys.argv = expand_patterns_file(sys.argv)
    sys.exit(main())

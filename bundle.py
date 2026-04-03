#!/usr/bin/env python3
"""
bundle.py — Сборщик исходного кода в единый Markdown-бандл
==========================================================
Назначение:
Собирает файлы проекта в один читаемый документ с автоматической обработкой кодировок,
сохраняя оригинальные байты при необходимости. Поддерживает гибкую фильтрацию по шаблонам.
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
  -p "*.cpp,tools/"           — добавить файлы/директории (через запятую или несколько раз)
  --patterns-file <file>      — загрузить шаблоны из файла (по одному на строку, # — комментарий)
  --ignore "test/"            — исключить пути из текущего набора
  --paths-only "*.log"        — добавить только пути, без содержимого
  --encoding "tools/:cp866"   — принудительно задать кодировку (напр. "*.bat:cp866")
  --no-binary-backupp "*.tmp" — отключить base64-дубли для шаблона
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
    """Нормализует шаблоны для интуитивного поведения (совместимость с Windows CMD)"""
    if pat.endswith('.*'):
        base = pat[:-2]
        # Если в базе уже есть *, fnmatch сам поймает расширения.
        # Если нет *, добавляем *, чтобы поймать и файлы без расширений
        return base + '*' if not base.endswith('*') else base
    if pat == '*.*':
        return '*'
    return pat

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
    # Нормализуем путь к формату с '/' (кроссплатформенно)
    path_str = str(path).replace('\\', '/')
    
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
        # Если шаблон содержит '/' — это полный путь к файлу
        if '/' in pattern:
            return path_str == pattern
        # Иначе — совпадение только по имени файла
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
            items.append((normalize_pattern(pat.strip()), val.strip()))
        else:
            items.append((normalize_pattern(part), True))  # для флагов вроде --no-binary-backup
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

    # Подготовка правил
    encoding_rules = []
    for enc_opt in args.encoding:
        encoding_rules.extend(parse_key_value_option(enc_opt))
    no_backup_rules = []
    for nb_opt in args.no_binary_backup:
        no_backup_rules.extend(parse_key_value_option(nb_opt))
    paths_only_rules = []
    for po_opt in args.paths_only:
        paths_only_rules.extend(parse_key_value_option(po_opt))

    all_paths = collect_all_paths(root)
    current_set = set()
    file_cache = {}  # rel_path -> {type, text, enc, is_bin, needs_b64, error}
    RED = "\033[91m"
    RESET = "\033[0m"

    # 1. Обработка паттернов включения с групповым выводом
    for pattern_str in args.patterns:
        sub_patterns = [normalize_pattern(p.strip()) for p in pattern_str.split(",") if p.strip()]
        for pat in sub_patterns:
            matched = []
            for p in all_paths:
                is_dir = (root / p).is_dir()
                if match_pattern(p, pat, is_dir):
                    matched.append(p)

            print(f"{pat} ({len(matched)})", file=sys.stderr)
            if not matched:
                print(f"  {RED}(не найдено){RESET}", file=sys.stderr)
            else:
                current_set.update(matched)
                for p in matched:
                    is_dir = (root / p).is_dir()
                    is_po = any(match_pattern(p, po, is_dir) for po, _ in paths_only_rules)

                    if is_po:
                        file_cache[p] = {"type": "path_only", "text": None, "enc": None, "is_bin": False, "needs_b64": False, "error": None}
                        print(f"  [PATH] {p}", file=sys.stderr)
                        continue

                    expl_enc = None
                    for ep, e in encoding_rules:
                        if match_pattern(p, ep, False):
                            expl_enc = e
                            break
                    disable_b64 = any(match_pattern(p, nb, False) for nb, _ in no_backup_rules)

                    text, det_enc, needs_b64, is_bin, err = read_file_with_encoding(root / p, expl_enc)
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
            ign_pats = [p.strip() for p in ign_str.split(",") if p.strip()]
            for p in list(current_set):
                is_dir = (root / p).is_dir()
                if any(match_pattern(p, ign, is_dir) for ign in ign_pats):
                    current_set.remove(p)

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
        if output_mode != 'stdout':
            out.write(f"# Bundle from `{root}`\n")

        sorted_paths = sorted(current_set)
        # Счётчики для финальной статистики
        utf8_count = converted_count = binary_count = paths_only_count = 0

        for rel in sorted_paths:
            is_dir = (root / rel).is_dir()
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
                out.write("## `{rel}` (binary)\n")
                out.write("```base64\n")
                with open(root / rel, "rb") as f:
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
                with open(root / rel, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n")
                converted_count += 1
            else:
                utf8_count += 1

        out.write("\n")
        # Финальная статистика
        print(f"\n✅ Записано {output_path if output_path else 'stdout'}", file=sys.stderr)
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
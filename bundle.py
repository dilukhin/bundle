#!/usr/bin/env python3
"""
bundle.py — Сборщик исходного кода в единый Markdown-бандл
==========================================================

Назначение:
Собирает файлы проекта в один читаемый документ для передачи LLM (ChatGPT и др.).
Автоматически обрабатывает разные кодировки (UTF-8, windows-1251, cp866 и др.),
сохраняя оригинальные байты в base64 для точного восстановления.

Поддерживаемые кодировки (автодетектирование):
  • utf-8, utf-8-sig (с BOM)
  • windows-1251 (cp1251) — кириллица Windows
  • cp866 — кириллица DOS
  • koi8-r — кириллица Unix
  • iso-8859-5 — кириллица ISO
  • ascii — латиница без диакритики
  • и другие текстовые кодировки

Полный список кодировок Python: https://docs.python.org/3/library/codecs.html#standard-encodings
Или выполните в Python: import encodings; help(encodings)

Формат бандла:
$# Bundle from `/путь/к/проекту`
$
$---
$## `путь/к/файлу.cpp`
$<!-- bundle:encoding=windows-1251 -->
$```cpp
$// содержимое, перекодированное в UTF-8 (читаемо для LLM)
$```
$
$## `путь/к/файлу.cpp` (original bytes)
$```base64
$// оригинальные байты в base64 (для восстановления)
$```

Особенности:
• Файлы в UTF-8 (включая UTF-8-BOM) сохраняются один раз без дублирования
• Бинарные файлы определяются по наличию нулевого байта (\x00) — только base64
• Все текстовые файлы перекодируются в UTF-8 с нормализацией окончаний строк до LF (\n)
• Оригинальные байты (включая CRLF) всегда доступны в base64-блоке
• Мета-информация в формате <!-- bundle:... --> (минимально интрузивный вариант)

Примеры использования:
  # Собрать проект с кодом на кириллице (win1251)
  python bundle.py . -o bundle.md -p "*.cpp,*.h"

  # Явно указать кодировку для определённых файлов
  python bundle.py . --encoding="*.txt:cp866,*.log:windows-1251"

  # Исключить директории
  python bundle.py . --ignore ".git,build,__pycache__"

Требования:
  pip install charset-normalizer

Запуск без параметров покажет краткую справку.
"""

import argparse
import os
import sys
import base64
import fnmatch
from pathlib import Path
from charset_normalizer import from_path


def show_short_help():
    """Показать краткую справку при запуске без параметров"""
    print("""
bundle.py — сборщик исходного кода в Markdown-бандл

Быстрый старт:
  python bundle.py . -o bundle.md -p "*.cpp,*.h,*.py"

Ключевые опции:
  -p "*.cpp,*.h"        — шаблоны файлов для включения
  --ignore ".git,build" — исключить директории
  --encoding "win1251"  — кодировка по умолчанию или "*.txt:cp866"

Полная справка: python bundle.py --help
Документация: см. комментарии в начале скрипта
""")
    sys.exit(0)


def is_binary_file(path, sample_size=1024):
    """
    Определить, является ли файл бинарным.
    Критерий: наличие нулевого байта (\x00) в первых 1024 байтах.
    Это надёжный признак бинарного файла (исполняемые, изображения, архивы).
    """
    try:
        with open(path, 'rb') as f:
            sample = f.read(sample_size)
            if b'\x00' in sample:
                return True
            return False
    except Exception:
        return True  # При ошибке чтения считаем бинарным


def normalize_encoding_name(enc):
    """Нормализовать название кодировки для вывода: utf_8 → utf-8"""
    if not enc:
        return "unknown"
    return enc.lower().replace('_', '-').replace('utf8', 'utf-8')


def read_file_with_encoding(path, explicit_encoding=None):
    """
    Прочитать файл с обработкой кодировок и окончаний строк.
    
    Возвращает кортеж:
      (текст_utf8_с_LF, исходная_кодировка, нужно_base64, является_бинарным, ошибка)
    
    Логика:
      1. Проверяем на бинарность по \x00
      2. Читаем как бинарные данные (сохраняем оригинальные байты)
      3. Детектируем кодировку или используем явную
      4. Декодируем в строку с универсальным режимом (сохраняем все \r и \n)
      5. Нормализуем окончания строк до LF (\n) для бандла
      6. Определяем, нужен ли base64 (если не UTF-8)
    """
    # Шаг 1: проверка на бинарность
    if is_binary_file(path):
        return None, "binary", True, True, None
    
    # Шаг 2: читаем бинарные данные (для base64 и детектирования)
    try:
        with open(path, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        return None, None, False, False, f"Ошибка чтения: {e}"
    
    # Шаг 3: определяем кодировку
    encoding = explicit_encoding
    if not encoding:
        results = from_path(path).best()
        if results:
            encoding = results.encoding
    
    # Fallback на UTF-8 если детектирование не сработало
    if not encoding:
        encoding = "utf-8"
    
    # Шаг 4: декодируем с сохранением всех символов (включая \r)
    try:
        # Используем errors='strict' чтобы поймать реальные ошибки
        text_with_original_line_endings = raw_bytes.decode(encoding)
        
        # Нормализуем окончания строк до LF (\n) для бандла
        # Это стандарт для Markdown и LLM
        normalized_text = text_with_original_line_endings.replace('\r\n', '\n').replace('\r', '\n')
        
        # Проверяем, был ли файл уже в UTF-8 (включая UTF-8-BOM)
        normalized_enc = normalize_encoding_name(encoding)
        is_utf8_family = normalized_enc in ['utf-8', 'utf-8-sig', 'utf-8-bom', 'utf8', 'utf8-sig']
        needs_base64 = not is_utf8_family
        
        return normalized_text, encoding, needs_base64, False, None
    except (UnicodeDecodeError, LookupError) as e:
        # Если декодирование не удалось — считаем бинарным
        return None, encoding, True, True, f"Декодирование {encoding} не удалось: {e}"


def collect_files(root, patterns, ignore_dirs):
    """Собрать список файлов по шаблонам, исключая игнорируемые директории"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        # Пропускаем игнорируемые директории
        rel_parts = dirpath.relative_to(root).parts
        if any(part in ignore_dirs for part in rel_parts if part):
            continue
        for name in filenames:
            rel = (dirpath / name).relative_to(root)
            if any(fnmatch.fnmatch(name, pat) for pat in patterns):
                files.append(rel)
    return sorted(files)


def main():
    # Показать справку при запуске без аргументов
    if len(sys.argv) == 1:
        show_short_help()
    
    ap = argparse.ArgumentParser(
        description="Сборщик исходного кода в единый Markdown-бандл с поддержкой разных кодировок",
        epilog="Пример: python bundle.py . -o bundle.md -p \"*.cpp,*.h\" --ignore \".git,build\""
    )
    ap.add_argument("root", nargs="?", default=".", help="Корневая директория проекта")
    ap.add_argument("-o", "--output", default="bundle.md", help="Имя выходного файла")
    ap.add_argument(
        "-p", "--patterns",
        default="*.cpp,*.h,*.hpp,*.c,*.py,*.md",
        help="Шаблоны файлов через запятую (glob-синтаксис)"
    )
    ap.add_argument(
        "--ignore",
        default=".git,node_modules,build,dist,__pycache__",
        help="Имена директорий для игнорирования через запятую"
    )
    ap.add_argument(
        "--encoding",
        default=None,
        help="Кодировка по умолчанию или маппинг: '*.txt:cp866,*.log:windows-1251'"
    )
    args = ap.parse_args()
    
    root = Path(args.root).resolve()
    if not root.exists():
        print(f"❌ Ошибка: путь не существует: {root}")
        return 1
    
    patterns = [p.strip() for p in args.patterns.split(",")]
    ignore_dirs = set(x.strip() for x in args.ignore.split(","))
    
    # Парсим маппинг кодировок
    encoding_map = {}
    default_encoding = None
    if args.encoding:
        parts = [p.strip() for p in args.encoding.split(",")]
        for part in parts:
            if ":" in part:
                pat, enc = part.split(":", 1)
                encoding_map[pat.strip()] = enc.strip()
            else:
                default_encoding = part.strip()
    
    files = collect_files(root, patterns, ignore_dirs)
    
    if not files:
        print(f"⚠️  Не найдено файлов по шаблонам: {args.patterns}")
        print(f"   Проверьте путь: {root}")
        return 1
    
    # Счётчики
    total_count = 0
    utf8_count = 0
    converted_count = 0
    binary_count = 0
    
    # Открываем выходной файл в текстовом режиме с фиксированным newline='\n'
    # Это гарантирует, что все \n останутся \n, а не превратятся в \r\n в Windows
    with open(args.output, "w", encoding="utf-8", newline='\n') as out:
        out.write(f"# Bundle from `{root}`\n\n")
        
        for rel in files:
            path = root / rel
            
            # Определяем явную кодировку по маппингу
            explicit_encoding = None
            name = rel.name
            for pat, enc in encoding_map.items():
                if fnmatch.fnmatch(name, pat):
                    explicit_encoding = enc
                    break
            if explicit_encoding is None:
                explicit_encoding = default_encoding
            
            # Читаем файл
            text, detected_enc, needs_base64, is_binary, error = read_file_with_encoding(
                path, explicit_encoding
            )
            
            out.write("---\n")
            out.write(f"## `{rel}`\n")
            
            if error:
                out.write(f"<!-- bundle:error={error} -->\n")
                out.write("```text\n")
                out.write(f"<<ОШИБКА: {error}>>\n")
                out.write("```\n\n")
                print(f"[ERR] {rel}: {error}")
                total_count += 1
                continue
            
            if is_binary:
                binary_count += 1
                total_count += 1
                norm_enc = normalize_encoding_name(detected_enc)
                out.write(f"<!-- bundle:binary=true encoding={norm_enc} -->\n")
                out.write(f"## `{rel}` (binary)\n")
                out.write("```base64\n")
                with open(path, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n\n")
                print(f"[BIN] {rel} ({norm_enc})")
                continue
            
            # Текстовый файл — сохраняем в UTF-8 с LF-окончаниями
            norm_enc = normalize_encoding_name(detected_enc)
            out.write(f"<!-- bundle:encoding={norm_enc} -->\n")
            lang = rel.suffix[1:] if rel.suffix else ""
            out.write(f"```{lang}\n")
            # Убеждаемся, что текст заканчивается одним переводом строки (LF)
            if text and not text.endswith('\n'):
                text += '\n'
            out.write(text)
            out.write("```\n")
            
            # Добавляем base64 только если файл НЕ был в UTF-8 изначально
            if needs_base64:
                converted_count += 1
                total_count += 1
                out.write(f"\n## `{rel}` (original bytes)\n")
                out.write("```base64\n")
                with open(path, "rb") as f:
                    out.write(base64.b64encode(f.read()).decode("ascii"))
                out.write("\n```\n\n")
                print(f"[CONV] {rel} ({norm_enc} → UTF-8 + base64)")
            else:
                utf8_count += 1
                total_count += 1
                print(f"[UTF8] {rel} ({norm_enc})")
            
            out.write("\n")
    
    print(f"\n✅ Записано {args.output}")
    print(f"   Всего файлов: {total_count}")
    print(f"   • UTF-8 (без дублирования): {utf8_count}")
    print(f"   • Конвертировано (с base64): {converted_count}")
    print(f"   • Бинарные: {binary_count}")
    print(f"\n💡 Совет: Для восстановления оригинала используйте base64-блоки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
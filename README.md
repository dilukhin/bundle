# bundle.py — сборщик исходного кода в Markdown-bundle

Текущая версия: `0.2.0`.

Утилита собирает выбранные файлы и каталоги в читаемый Markdown-документ. Текст сохраняется в обычном виде, бинарные данные и оригинальные байты преобразованных текстовых файлов — в Base64. Формат содержит машинные идентификаторы записей, Git-метаданные и SHA-256 manifest.

Номер версии хранится в одном месте: `bundle_model.py::__version__`.

## Требования

- Python 3.9 или новее;
- `charset-normalizer` версии 3.x;
- Git необязателен: без него bundle создаётся с состоянием `not-a-git-repository`.

Установка зависимости:

```bash
python -m pip install "charset-normalizer>=3.3,<4"
```

Проверка версии:

```bash
python bundle.py --version
```

## Быстрый старт

```bash
python bundle.py . -p "*.cpp,*.h" -o bundle.md
python bundle.py . -p "src/" -a bundle.md
python bundle.py . --patterns-file files.txt -o bundle.md
```

Без `-o` и `-a` результат выводится в stdout.

Запуск без параметров показывает краткий usage. `--help` показывает подробную справку.

## Выбор файлов

`-p` или `--patterns` можно указывать несколько раз. В одном значении допускается список через запятую.

| Пример | Поведение |
|---|---|
| `*.cpp` | Имена файлов во всём дереве |
| `src/*.py` | Один компонент пути после `src/` |
| `tests/**/*.json` | Рекурсивный glob |
| `src/main.py` | Точный путь внутри корня |
| `./CMakeLists.txt` | Точный файл в корне |
| `../logs/build.log` | Точный внешний файл |
| `C:\temp\diff.txt` | Абсолютный Windows-путь |
| `tools/` | Каталоги внутри `tools/` согласно текущей семантике селектора |

Поддерживаются `*`, `?`, `[]` и `**`. Windows-разделители нормализуются в `/`.

`*.*` нормализуется в `*`. Маска `name.*` нормализуется в `name*` для совместимости с привычным поведением Windows CMD.

## Модификаторы

| Опция | Назначение |
|---|---|
| `--patterns-file FILE` | Прочитать шаблоны из UTF-8 или Windows-1251 |
| `--ignore PATTERN` | Исключить выбранные записи |
| `--paths-only PATTERN` | Сохранить только путь без содержимого |
| `--encoding PATTERN:ENCODING` | Явно задать кодировку |
| `--no-binary-backup PATTERN` | Не сохранять Base64 исходных байтов преобразованного текста |
| `--no-metadata` | Не добавлять расширенный блок метаданных |
| `--no-manifest` | Не добавлять SHA-256 manifest |
| `-o FILE` | Атомарно записать новый bundle |
| `-a FILE` | Атомарно добавить самостоятельный фрагмент |

Абсолютный Windows-путь в `--encoding` разделяется по последнему двоеточию:

```text
python bundle.py D:\Projects\App -p "C:\temp\legacy.txt" --encoding "C:\temp\legacy.txt:cp1251" -o selected.md
```

## Формат фрагмента

Каждый фрагмент содержит обязательные границы и версию формата:

```markdown
<!-- bundle:fragment:start -->
<!-- bundle:format=2 -->
<!-- bundle:generator=bundle.py version=0.2.0 -->
...
<!-- bundle:fragment:end -->
```

При `-a` новый фрагмент не изменяет ранее записанные фрагменты.

Подробная спецификация находится в `FORMAT.md`.

## Git-метаданные

По умолчанию в bundle записываются:

- абсолютный корень Git-репозитория или bundle root;
- bundle root;
- ветка или `detached HEAD`;
- полный commit SHA;
- время создания с timezone;
- состояние `clean`, `dirty` или `not-a-git-repository`;
- список изменённых и новых путей для dirty-дерева;
- версия генератора;
- число файловых записей.

Содержимое файлов и значения переменных окружения в Git-метаданные не попадают.

## SHA-256 manifest

Manifest содержит SHA-256 исходных байтов каждого текстового и бинарного файла:

```text
<sha256>  i:src/main.py
<sha256>  e:../logs/build.log
```

`path-only`-записи и каталоги в manifest не входят. Порядок совпадает с каноническим порядком записей.

## Точное и нормализованное представление

Машинный блок содержимого содержит поле:

```text
Restoration: exact|lossy
```

`exact` означает, что в bundle есть исходные байты либо текстовое представление побайтово совпадает с исходным файлом.

`lossy` означает, что сохранено только нормализованное текстовое представление. Причиной могут быть CRLF/CR, BOM, отсутствие завершающего LF или `--no-binary-backup` для другой кодировки. Исходный SHA-256 всё равно остаётся в manifest.

Извлечение пока не реализовано. Правила явного извлечения нормализованного содержимого описаны в issue №4.

## Вложенный Markdown и обратные апострофы

Текст не экранируется. Для каждого fenced-блока автоматически выбирается длина внешнего fence, превышающая любую последовательность обратных апострофов в содержимом. Поэтому в bundle можно безопасно включать Markdown-файлы с собственными блоками:

````markdown
```python
print("nested")
```
````

Содержимое файла при этом не изменяется из-за экранирования.

## Внешние пути

Внешний файл на том же диске получает относительный путь:

```text
Path: "../logs/build.log"
Key: e:../logs/build.log
```

Для другого диска Windows используется:

```text
Path: "@drive/C/temp/diff.txt"
Key: e:@drive/C/temp/diff.txt
```

Для UNC используется:

```text
Path: "@unc/server/share/dir/file.txt"
Key: e:@unc/server/share/dir/file.txt
```

Абсолютный исходный путь в bundle не записывается. `@drive` и `@unc` являются идентификаторами внешней записи, а не путями автоматического извлечения.

## Проверка разработки

```bash
python -m compileall -q bundle.py bundle_model.py bundle_paths.py \
  bundle_git.py bundle_select.py bundle_writer.py bundle_serialize.py \
  bundle_output.py tests
python -m unittest discover -s tests -v
python bundle.py --version
python bundle.py --help
python bundle.py
```

GitHub Actions выполняет тесты на Ubuntu и Windows с Python 3.9 и 3.13.

## Автор

Дмитрий Илюхин (`dilukhin@hotmail.com`).

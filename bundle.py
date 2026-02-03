#!/usr/bin/env python3
"""
bundle.py — Project source bundler
=================================

This utility collects multiple source files from a directory tree and
bundles them into a single Markdown document (bundle.md by default).

It is designed for:
  - uploading whole projects into ChatGPT / LLMs
  - code reviews
  - architecture analysis
  - long-term snapshots of a codebase

Each file is embedded in Markdown as:

    ## relative/path/to/file.ext
    ```ext
    file contents
    ```

So syntax highlighting is preserved when viewing or pasting.

------------------------------------------------------------
Basic usage
------------------------------------------------------------

    python bundle.py
    python bundle.py . -o bundle.md
    python bundle.py ../myproject -o snapshot.md

------------------------------------------------------------
Selecting files
------------------------------------------------------------

Use --patterns to control which files are included:

    -p "*.cpp,*.h,*.hpp,*.py,*.md"

Patterns are matched against filenames using glob syntax.

------------------------------------------------------------
Ignoring directories
------------------------------------------------------------

Use --ignore to exclude directories by name:

    --ignore ".git,build,node_modules,dist,__pycache__"

If any directory in a file's path matches one of these names,
that file is skipped.

------------------------------------------------------------
Output format
------------------------------------------------------------

The output file contains:

    # Bundle from `/absolute/project/path`

    ---
    ## `src/main.cpp`
    ```cpp
    <file contents>
    ```

    ---
    ## `include/foo.h`
    ```h
    <file contents>
    ```

This format works well with Markdown renderers and LLMs.

------------------------------------------------------------
Typical workflow
------------------------------------------------------------

    python bundle.py . -o bundle.md -p "*.cpp,*.h,*.cmake"

Then upload bundle.md into ChatGPT and ask:

    "Analyze this codebase"

------------------------------------------------------------
Limitations
------------------------------------------------------------

- Does not read .gitignore (only --ignore list)
- Includes files purely by filename glob
- Does not detect binary files
- Does not trim large files

These can be extended if needed.
"""

import argparse
import os
import fnmatch
from pathlib import Path


def should_ignore(path, ignore_dirs):
    for part in path.parts:
        if part in ignore_dirs:
            return True
    return False


def collect_files(root, patterns, ignore_dirs):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        if should_ignore(dirpath, ignore_dirs):
            continue

        for name in filenames:
            p = dirpath / name
            rel = p.relative_to(root)

            if any(fnmatch.fnmatch(name, pat) for pat in patterns):
                files.append(rel)

    return sorted(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("-o", "--output", default="bundle.md")
    ap.add_argument(
        "-p", "--patterns",
        default="*.cpp,*.h,*.hpp,*.c,*.py,*.md",
        help="Comma-separated glob patterns"
    )
    ap.add_argument(
        "--ignore",
        default=".git,node_modules,build,dist,__pycache__",
        help="Comma-separated dir names to ignore"
    )

    args = ap.parse_args()

    root = Path(args.root).resolve()
    patterns = [p.strip() for p in args.patterns.split(",")]
    ignore_dirs = set(x.strip() for x in args.ignore.split(","))

    files = collect_files(root, patterns, ignore_dirs)

    with open(args.output, "w", encoding="utf-8") as out:
        out.write(f"# Bundle from `{root}`\n\n")

        for rel in files:
            path = root / rel
            out.write("\n---\n\n")
            out.write(f"## `{rel}`\n\n")
            out.write("```")
            out.write(rel.suffix[1:] if rel.suffix else "")
            out.write("\n")

            try:
                with open(path, "r", encoding="utf-8") as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"<<ERROR: {e}>>")

            out.write("\n```\n")

    print(f"Written {args.output} with {len(files)} files")


if __name__ == "__main__":
    main()

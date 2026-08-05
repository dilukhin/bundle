"""Безопасная публикация сформированного фрагмента bundle."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from bundle_model import BundleError

def _copy_file(source_path, destination_stream):
    with open(source_path, "rb") as source:
        shutil.copyfileobj(source, destination_stream)

def publish_write(fragment_path, output_path):
    output = Path(output_path)
    parent = output.parent if output.parent != Path("") else Path(".")
    if not parent.exists():
        raise BundleError(f"каталог вывода не существует: {parent}")

    handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=os.fspath(parent), prefix=f".{output.name}.", suffix=".tmp"
    )
    temp_name = handle.name
    try:
        with handle:
            _copy_file(fragment_path, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

def publish_append(fragment_path, output_path):
    output = Path(output_path)
    parent = output.parent if output.parent != Path("") else Path(".")
    if not parent.exists():
        raise BundleError(f"каталог вывода не существует: {parent}")

    handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=os.fspath(parent), prefix=f".{output.name}.", suffix=".tmp"
    )
    temp_name = handle.name
    try:
        with handle:
            tail = b""
            if output.exists():
                with open(output, "rb") as current:
                    shutil.copyfileobj(current, handle)
                    if current.seekable():
                        current.seek(max(0, current.tell() - 2))
                        tail = current.read()
            if handle.tell() > 0:
                if tail.endswith(b"\n\n"):
                    pass
                elif tail.endswith(b"\n"):
                    handle.write(b"\n")
                else:
                    handle.write(b"\n\n")
            _copy_file(fragment_path, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

def publish_stdout(fragment_path):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")
    with open(fragment_path, "r", encoding="utf-8", newline="") as source:
        shutil.copyfileobj(source, sys.stdout)

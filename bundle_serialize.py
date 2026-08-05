import base64
import json
import os

from bundle_model import (
    BUNDLE_FORMAT_VERSION,
    __version__,
    normalize_encoding_name,
    serialized_text_payload,
)
from bundle_git import create_file_snapshot


def _longest_backtick_run(text):
    longest = 0
    current = 0
    for character in text:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _fence_for(text, minimum=3):
    return "`" * max(minimum, _longest_backtick_run(text) + 1)


def _write_fenced_block(out, content, language=""):
    fence = _fence_for(content)
    out.write(f"{fence}{language}\n")
    out.write(content)
    if content and not content.endswith("\n"):
        out.write("\n")
    out.write(f"{fence}\n")


def _inline_code(value):
    fence = "`" * max(1, _longest_backtick_run(value) + 1)
    needs_padding = value.startswith(("`", " ")) or value.endswith(("`", " "))
    content = f" {value} " if needs_padding else value
    return f"{fence}{content}{fence}"


def _write_heading(out, display_path, is_directory=False):
    value = display_path.as_posix() + ("/" if is_directory else "")
    out.write(f"## {_inline_code(value)}\n")


def _write_machine_entry(out, entry, entry_type, size=None, restoration=None):
    lines = [
        f"Kind: {entry.kind}",
        f"Key: {entry.key}",
        f"Path: {json.dumps(entry.display_path.as_posix(), ensure_ascii=False)}",
    ]
    if entry.repository_path is not None:
        lines.append(
            f"Repository path: {json.dumps(entry.repository_path, ensure_ascii=False)}"
        )
    lines.append(f"Type: {entry_type}")
    if size is not None:
        lines.append(f"Size: {size}")
    if restoration is not None:
        lines.append(f"Restoration: {restoration}")
    _write_fenced_block(out, "\n".join(lines) + "\n", "bundle-entry")


def write_fragment_header(out):
    out.write("<!-- bundle:fragment:start -->\n")
    out.write(f"<!-- bundle:format={BUNDLE_FORMAT_VERSION} -->\n")
    out.write(f"<!-- bundle:generator=bundle.py version={__version__} -->\n\n")
    out.write("# Bundle\n")


def write_metadata(out, metadata, included_files_count):
    lines = [
        f"Repository: {metadata.repository_path}",
        f"Bundle root: {metadata.bundle_root}",
        f"Branch: {metadata.branch}",
        f"Commit: {metadata.commit}",
        f"Generated at: {metadata.generated_at}",
        f"Git status: {metadata.git_status}",
        f"Bundle generator/version: bundle.py {__version__}",
        f"Included files count: {included_files_count}",
    ]
    if metadata.git_status == "dirty":
        lines.append("Uncommitted files:")
        lines.extend(f"- {item}" for item in metadata.uncommitted_files)

    out.write("\n<!-- bundle:metadata:start -->\n")
    out.write("## Bundle metadata\n\n")
    _write_fenced_block(out, "\n".join(lines) + "\n", "text")
    out.write("<!-- bundle:metadata:end -->\n")


def write_directory_entry(out, entry):
    out.write("\n---\n")
    _write_heading(out, entry.display_path, is_directory=True)
    _write_machine_entry(out, entry, "directory")
    _write_fenced_block(out, "# directory\n", "text")


def write_path_only_entry(out, entry):
    out.write("\n---\n")
    _write_heading(out, entry.display_path)
    _write_machine_entry(out, entry, "path-only")
    _write_fenced_block(out, "# path only\n", "text")


def write_content_entry(out, entry, snapshot):
    out.write("\n---\n")
    _write_heading(out, entry.display_path)

    if snapshot.entry_type == "binary":
        _write_machine_entry(
            out, entry, snapshot.entry_type, len(snapshot.raw_bytes), restoration="exact"
        )
        out.write("<!-- bundle:binary=true encoding=base64 -->\n")
        _write_fenced_block(
            out, base64.b64encode(snapshot.raw_bytes).decode("ascii"), "base64"
        )
        return "binary"

    original_bytes_saved = snapshot.needs_base64 and not entry.disable_binary_backup
    restoration = "exact" if snapshot.text_is_exact or original_bytes_saved else "lossy"
    _write_machine_entry(
        out, entry, snapshot.entry_type, len(snapshot.raw_bytes), restoration=restoration
    )

    normalized_encoding = normalize_encoding_name(snapshot.encoding)
    language = entry.display_path.suffix[1:] if entry.display_path.suffix else ""
    out.write(f"<!-- bundle:encoding={normalized_encoding} -->\n")
    _write_fenced_block(out, serialized_text_payload(snapshot.text), language)

    if original_bytes_saved:
        out.write("\n### Original bytes\n")
        _write_fenced_block(
            out, base64.b64encode(snapshot.raw_bytes).decode("ascii"), "base64"
        )

    return "converted" if snapshot.needs_base64 else "utf8"


def write_manifest(out, manifest_entries):
    content = "".join(f"{digest}  {key}\n" for digest, key in manifest_entries)
    out.write("\n<!-- bundle:manifest:start -->\n")
    out.write("## Bundle manifest\n\n")
    _write_fenced_block(out, content, "text")
    out.write("<!-- bundle:manifest:end -->\n")


def build_fragment(fragment_path, entries, metadata, include_metadata, include_manifest):
    included_files_count = sum(1 for entry in entries if not entry.is_directory)
    manifest_entries = []
    counts = {"utf8": 0, "converted": 0, "binary": 0, "path_only": 0}

    with open(fragment_path, "w", encoding="utf-8", newline="\n") as out:
        write_fragment_header(out)
        if include_metadata:
            write_metadata(out, metadata, included_files_count)

        for entry in entries:
            if entry.is_directory:
                write_directory_entry(out, entry)
                continue
            if entry.path_only:
                write_path_only_entry(out, entry)
                counts["path_only"] += 1
                continue

            snapshot = create_file_snapshot(
                entry.source_path,
                explicit_encoding=entry.explicit_encoding,
                need_sha256=include_manifest,
            )
            category = write_content_entry(out, entry, snapshot)
            counts[category] += 1
            if include_manifest:
                manifest_entries.append((snapshot.sha256, entry.key))

        if include_manifest:
            write_manifest(out, manifest_entries)
        out.write("\n<!-- bundle:fragment:end -->\n")
        out.flush()
        os.fsync(out.fileno())

    return included_files_count, counts

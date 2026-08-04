import base64
import json
import os

from bundle_model import BUNDLE_FORMAT_VERSION, __version__, normalize_encoding_name
from bundle_git import create_file_snapshot

def _write_machine_entry(out, entry, entry_type, size=None):
    out.write("```bundle-entry\n")
    out.write(f"Kind: {entry.kind}\n")
    out.write(f"Key: {entry.key}\n")
    out.write(f"Path: {json.dumps(entry.display_path.as_posix(), ensure_ascii=False)}\n")
    if entry.repository_path is not None:
        out.write(
            f"Repository path: {json.dumps(entry.repository_path, ensure_ascii=False)}\n"
        )
    out.write(f"Type: {entry_type}\n")
    if size is not None:
        out.write(f"Size: {size}\n")
    out.write("```\n")

def write_fragment_header(out):
    out.write("<!-- bundle:fragment:start -->\n")
    out.write(f"<!-- bundle:format={BUNDLE_FORMAT_VERSION} -->\n")
    out.write(f"<!-- bundle:generator=bundle.py version={__version__} -->\n\n")
    out.write("# Bundle\n")

def write_metadata(out, metadata, included_files_count):
    out.write("\n<!-- bundle:metadata:start -->\n")
    out.write("## Bundle metadata\n\n")
    out.write("```text\n")
    out.write(f"Repository: {metadata.repository_path}\n")
    out.write(f"Bundle root: {metadata.bundle_root}\n")
    out.write(f"Branch: {metadata.branch}\n")
    out.write(f"Commit: {metadata.commit}\n")
    out.write(f"Generated at: {metadata.generated_at}\n")
    out.write(f"Git status: {metadata.git_status}\n")
    out.write(f"Bundle generator/version: bundle.py {__version__}\n")
    out.write(f"Included files count: {included_files_count}\n")
    if metadata.git_status == "dirty":
        out.write("Uncommitted files:\n")
        for item in metadata.uncommitted_files:
            out.write(f"- {item}\n")
    out.write("```\n")
    out.write("<!-- bundle:metadata:end -->\n")

def write_directory_entry(out, entry):
    out.write("\n---\n")
    out.write(f"## `{entry.display_path.as_posix()}/`\n")
    _write_machine_entry(out, entry, "directory")
    out.write("```text\n# directory\n```\n")

def write_path_only_entry(out, entry):
    out.write("\n---\n")
    out.write(f"## `{entry.display_path.as_posix()}`\n")
    _write_machine_entry(out, entry, "path-only")
    out.write("```text\n# path only\n```\n")

def write_content_entry(out, entry, snapshot):
    out.write("\n---\n")
    out.write(f"## `{entry.display_path.as_posix()}`\n")
    _write_machine_entry(out, entry, snapshot.entry_type, len(snapshot.raw_bytes))

    if snapshot.entry_type == "binary":
        out.write("<!-- bundle:binary=true encoding=base64 -->\n")
        out.write("```base64\n")
        out.write(base64.b64encode(snapshot.raw_bytes).decode("ascii"))
        out.write("\n```\n")
        return "binary"

    normalized_encoding = normalize_encoding_name(snapshot.encoding)
    language = entry.display_path.suffix[1:] if entry.display_path.suffix else ""
    out.write(f"<!-- bundle:encoding={normalized_encoding} -->\n")
    out.write(f"```{language}\n")
    text = snapshot.text or ""
    if text and not text.endswith("\n"):
        text += "\n"
    out.write(text)
    out.write("```\n")

    if snapshot.needs_base64 and not entry.disable_binary_backup:
        out.write("\n### Original bytes\n")
        out.write("```base64\n")
        out.write(base64.b64encode(snapshot.raw_bytes).decode("ascii"))
        out.write("\n```\n")
        return "converted"
    return "utf8"

def write_manifest(out, manifest_entries):
    out.write("\n<!-- bundle:manifest:start -->\n")
    out.write("## Bundle manifest\n\n")
    out.write("```text\n")
    for digest, key in manifest_entries:
        out.write(f"{digest}  {key}\n")
    out.write("```\n")
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


from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
LOCK = ROOT / "docs-sources.lock.json"
REGISTRY = ROOT / "docs-sources.json"
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
MARKER = "<!-- generated-doc: {repository} -->"


def fail(message: str) -> None:
    raise SystemExit(message)


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot read {label}: {error}")
    if not isinstance(value, dict):
        fail(f"{label} must contain an object")
    return value


def require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        fail(f"{label} has invalid keys")


def relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail(f"{label} must contain a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        fail(f"{label} must contain a safe relative path")
    return value


def parse_registry() -> dict[str, tuple[tuple[str, str], ...]]:
    document = read_object(REGISTRY, "docs-sources.json")
    require_keys(
        document,
        {"schema_version", "publication_repository", "sources"},
        "docs-sources.json",
    )
    if document["schema_version"] != 1:
        fail("docs-sources.json has an invalid schema version")
    if document["publication_repository"] != "GroundSystems/groundhog":
        fail("docs-sources.json has an invalid publication repository")
    sources = document["sources"]
    if not isinstance(sources, dict) or list(sources) != sorted(sources):
        fail("docs-sources.json sources must be a sorted object")

    result: dict[str, tuple[tuple[str, str], ...]] = {}
    all_destinations: list[str] = []
    for repository, raw_config in sources.items():
        if not isinstance(raw_config, dict):
            fail(f"source configuration must contain an object: {repository}")
        require_keys(raw_config, {"exports"}, f"source configuration for {repository}")
        raw_exports = raw_config["exports"]
        if not isinstance(raw_exports, list) or not raw_exports:
            fail(f"source exports must contain a list: {repository}")
        exports: list[tuple[str, str]] = []
        for raw_export in raw_exports:
            if not isinstance(raw_export, dict):
                fail(f"source export must contain an object: {repository}")
            require_keys(raw_export, {"source", "destination"}, "source export")
            source = relative_path(raw_export["source"], "source export")
            destination = relative_path(raw_export["destination"], "export destination")
            exports.append((destination, source))
            all_destinations.append(destination)
        if exports != sorted(exports):
            fail(f"source exports must be sorted: {repository}")
        result[repository] = tuple(exports)

    for index, left in enumerate(sorted(all_destinations)):
        for right in sorted(all_destinations)[index + 1 :]:
            if left == right or left.startswith(right + "/") or right.startswith(left + "/"):
                fail(f"generated destinations overlap: {left} and {right}")
    return result


def export_for_destination(
    destination: str, exports: tuple[tuple[str, str], ...]
) -> tuple[str, str] | None:
    for export_destination, export_source in exports:
        if PurePosixPath(export_destination).suffix:
            if destination == export_destination:
                return export_destination, export_source
        elif destination.startswith(export_destination + "/"):
            return export_destination, export_source
    return None


def expected_source_path(
    destination: str, export_destination: str, export_source: str
) -> str:
    if destination == export_destination:
        return export_source
    suffix = destination.removeprefix(export_destination + "/")
    return f"{export_source}/{suffix}"


def generated_files(exports: tuple[tuple[str, str], ...]) -> set[str]:
    result: set[str] = set()
    for destination, _source in exports:
        path = ROOT / destination
        if PurePosixPath(destination).suffix:
            if path.is_file():
                result.add(destination)
            continue
        if not path.exists():
            continue
        if not path.is_dir() or path.is_symlink():
            fail(f"generated destination must be a directory: {destination}")
        for child in path.rglob("*"):
            if child.is_symlink():
                fail(f"generated files must not use symbolic links: {child}")
            if child.is_file():
                result.add(child.relative_to(ROOT).as_posix())
    return result


def check_generated_files(
    registry: dict[str, tuple[tuple[str, str], ...]]
) -> tuple[int, int]:
    document = read_object(LOCK, "docs-sources.lock.json")
    require_keys(document, {"schema_version", "sources"}, "docs-sources.lock.json")
    if document["schema_version"] != 1:
        fail("docs-sources.lock.json has an invalid schema version")
    sources = document["sources"]
    if not isinstance(sources, dict) or list(sources) != sorted(sources):
        fail("docs-sources.lock.json sources must be a sorted object")
    if set(sources) != set(registry):
        fail("the source registry and provenance lock do not match")

    seen: set[str] = set()
    pending = 0
    for repository, source_lock in sources.items():
        if not isinstance(source_lock, dict):
            fail(f"source lock must contain an object: {repository}")
        require_keys(source_lock, {"commit", "files"}, f"source lock for {repository}")
        commit = source_lock["commit"]
        if commit is None:
            pending += 1
        elif not isinstance(commit, str) or REVISION.fullmatch(commit) is None:
            fail(f"source lock has an invalid commit: {repository}")
        files = source_lock["files"]
        if not isinstance(files, dict) or list(files) != sorted(files):
            fail(f"locked files must be a sorted object: {repository}")
        if set(files) != generated_files(registry[repository]):
            fail(f"generated files do not match the lock: {repository}")

        for destination, record in files.items():
            if destination in seen:
                fail(f"multiple sources own this file: {destination}")
            seen.add(destination)
            if not isinstance(record, dict):
                fail(f"file lock must contain an object: {destination}")
            require_keys(record, {"source", "sha256"}, f"file lock for {destination}")
            source = relative_path(record["source"], f"source path for {destination}")
            digest = record["sha256"]
            if not isinstance(digest, str) or HASH.fullmatch(digest) is None:
                fail(f"file lock has an invalid hash: {destination}")
            selected_export = export_for_destination(destination, registry[repository])
            if selected_export is None:
                fail(f"file lock uses an unowned destination: {destination}")
            if source != expected_source_path(destination, *selected_export):
                fail(f"file lock has an invalid source path: {destination}")
            path = ROOT / destination
            if not path.is_file() or path.is_symlink():
                fail(f"generated documentation file is missing: {destination}")
            data = path.read_bytes()
            actual = "sha256:" + hashlib.sha256(data).hexdigest()
            if actual != digest:
                fail(f"generated documentation changed directly: {destination}")
            if path.suffix.casefold() in {".md", ".mdx"}:
                marker = MARKER.format(repository=repository)
                if marker not in data.decode("utf-8"):
                    fail(f"generated documentation has no source marker: {destination}")
    return len(seen), pending


def resolve_link(source: Path, raw_target: str) -> Path | None:
    target = unquote(raw_target.strip().split(maxsplit=1)[0])
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None

    target = target.split("#", 1)[0].split("?", 1)[0]
    if target.startswith("/"):
        candidate = DOCS / target.removeprefix("/")
    else:
        candidate = source.parent / target

    if candidate.exists():
        return candidate.resolve()
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    return candidate.resolve()


def main() -> None:
    registry = parse_registry()
    generated_count, pending_count = check_generated_files(registry)
    config = read_object(DOCS / "docs.json", "docs/docs.json")
    missing: list[str] = []

    pages = [
        page
        for group in config["navigation"]["groups"]
        for page in group["pages"]
    ]
    for page in pages:
        path = DOCS / f"{page}.md"
        if not path.is_file():
            missing.append(f"navigation page: {path.relative_to(ROOT)}")

    markdown_files = sorted(
        path for path in ROOT.rglob("*.md") if ".git" not in path.parts
    )
    checked_links = 0
    for source in markdown_files:
        for raw_target in LINK.findall(source.read_text(encoding="utf-8")):
            target = resolve_link(source, raw_target)
            if target is None:
                continue
            checked_links += 1
            if not target.exists():
                missing.append(f"{source.relative_to(ROOT)}: {raw_target}")

    if missing:
        fail("missing documentation targets:\n" + "\n".join(missing))

    print(
        f"checked {len(pages)} navigation pages, {generated_count} generated files, "
        f"and {checked_links} local links"
    )
    if pending_count:
        print(f"pending first publication for {pending_count} source")


if __name__ == "__main__":
    main()

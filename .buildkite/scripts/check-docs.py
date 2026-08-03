from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
PAGE_SUFFIXES = (".md", ".mdx")


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


def navigation_pages(value: Any, label: str = "navigation") -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "pages":
                if not isinstance(child, list):
                    fail(f"{label}.pages must contain a list")
                for index, page in enumerate(child):
                    if isinstance(page, str):
                        if not page:
                            fail(f"{label}.pages[{index}] must not be empty")
                        yield page
                    elif isinstance(page, dict):
                        yield from navigation_pages(page, f"{label}.pages[{index}]")
                    else:
                        fail(f"{label}.pages[{index}] must contain a page or group")
            elif isinstance(child, (dict, list)):
                yield from navigation_pages(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from navigation_pages(child, f"{label}[{index}]")


def page_candidates(path: Path) -> tuple[Path, ...]:
    if path.suffix.casefold() in PAGE_SUFFIXES:
        return (path,)
    return (
        path,
        *(Path(f"{path}{suffix}") for suffix in PAGE_SUFFIXES),
        *(path / f"index{suffix}" for suffix in PAGE_SUFFIXES),
    )


def resolve_page(path: Path) -> Path | None:
    for candidate in page_candidates(path):
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_link(source: Path, raw_target: str) -> Path | None:
    target = unquote(raw_target.strip().split(maxsplit=1)[0])
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None

    target = target.split("#", 1)[0].split("?", 1)[0]
    path = DOCS / target.removeprefix("/") if target.startswith("/") else source.parent / target
    resolved = resolve_page(path) or page_candidates(path)[0].resolve()
    try:
        resolved.relative_to(DOCS.resolve())
    except ValueError:
        fail(
            "local documentation link must stay inside docs: "
            f"{source.relative_to(ROOT)}: {raw_target}"
        )
    return resolved


def main() -> None:
    config = read_object(DOCS / "docs.json", "docs/docs.json")
    navigation = config.get("navigation")
    if not isinstance(navigation, dict):
        fail("docs/docs.json navigation must contain an object")

    pages = list(navigation_pages(navigation))
    if not pages:
        fail("docs/docs.json navigation must contain at least one page")
    if len(pages) != len(set(pages)):
        fail("docs/docs.json navigation contains a duplicate page")

    missing: list[str] = []
    for page in pages:
        if page.startswith(("http://", "https://")):
            continue
        page_path = PurePosixPath(page)
        if (
            page_path.is_absolute()
            or "\\" in page
            or any(part in {"", ".", ".."} for part in page.split("/"))
        ):
            fail(f"navigation page must contain a safe relative path: {page}")
        if resolve_page(DOCS / page.removeprefix("/")) is None:
            missing.append(f"navigation page: docs/{page}")

    markdown_files = sorted((*DOCS.rglob("*.md"), *DOCS.rglob("*.mdx")))
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

    print(f"checked {len(pages)} navigation pages and {checked_links} local links")


if __name__ == "__main__":
    main()

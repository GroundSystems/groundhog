from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


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
    config = json.loads((DOCS / "docs.json").read_text())
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

    markdown_files = sorted(ROOT.rglob("*.md"))
    checked_links = 0
    for source in markdown_files:
        for raw_target in LINK.findall(source.read_text()):
            target = resolve_link(source, raw_target)
            if target is None:
                continue
            checked_links += 1
            if not target.exists():
                missing.append(
                    f"{source.relative_to(ROOT)}: {raw_target}"
                )

    if missing:
        raise SystemExit("missing documentation targets:\n" + "\n".join(missing))

    print(
        f"checked {len(pages)} navigation pages and "
        f"{checked_links} local Markdown links"
    )


if __name__ == "__main__":
    main()

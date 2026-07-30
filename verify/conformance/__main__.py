"""Validate the public OpenAPI document and optionally test a Groundhog binary."""

from __future__ import annotations

import argparse
from pathlib import Path

from .live import LiveError, run as run_live
from .validate import ContractError, load_document, validate_document


def main(argv: list[str] | None = None) -> int:
    """Run static validation and optional live conformance checks."""
    parser = argparse.ArgumentParser(prog="python -m verify.conformance")
    parser.add_argument("--document", type=Path, default=Path("openapi.yaml"))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--history-seed", type=int, default=0)
    arguments = parser.parse_args(argv)
    if arguments.history is not None and arguments.binary is None:
        parser.error("--history requires --binary")

    try:
        document = load_document(arguments.document)
        validate_document(document)
        if arguments.binary is not None:
            run_live(
                arguments.binary,
                arguments.document,
                arguments.history,
                arguments.history_seed,
            )
    except (ContractError, LiveError, OSError) as error:
        print(error)
        return 1

    if arguments.binary is None:
        print(f"validated {arguments.document}")
    else:
        print(f"validated {arguments.binary} against {arguments.document}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

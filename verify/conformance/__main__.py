"""Validate the public OpenAPI document and optionally test a Groundhog binary."""

from __future__ import annotations

import argparse
from pathlib import Path

from verify.backend import BackendOptions

from .live import LiveError, run as run_live
from .validate import ContractError, load_document, validate_document


def main(argv: list[str] | None = None) -> int:
    """Run static validation and optional live conformance checks."""
    parser = argparse.ArgumentParser(prog="python -m verify.conformance")
    parser.add_argument("--document", type=Path, default=Path("openapi.yaml"))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--history-seed", type=int, default=0)
    parser.add_argument("--backend", choices=("local", "s3"), default="local")
    parser.add_argument("--s3-bucket")
    parser.add_argument("--s3-region")
    parser.add_argument("--s3-prefix")
    parser.add_argument(
        "--query",
        action="store_true",
        help="enable and exercise the authenticated local Query and Catalog routes",
    )
    arguments = parser.parse_args(argv)
    if arguments.history is not None and arguments.binary is None:
        parser.error("--history requires --binary")
    backend = BackendOptions(
        arguments.backend,
        arguments.s3_bucket,
        arguments.s3_region,
        arguments.s3_prefix,
    )
    try:
        backend.validate()
    except ValueError as error:
        parser.error(str(error))
    if arguments.query and backend.name != "local":
        parser.error("--query requires --backend local")

    try:
        document = load_document(arguments.document)
        validate_document(document)
        if arguments.binary is not None:
            run_live(
                arguments.binary,
                arguments.document,
                arguments.history,
                arguments.history_seed,
                backend,
                arguments.query,
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

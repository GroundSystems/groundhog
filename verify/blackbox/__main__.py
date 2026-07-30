"""Run the executable Groundhog black-box verifier."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .history import canonical_json
from .scenarios import (
    run_append_scenarios,
    run_replay_scenarios,
    run_retirement_race_scenarios,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m verify.blackbox")
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--retirement-iterations", type=int, default=8)
    arguments = parser.parse_args(argv)
    arguments.output.mkdir(parents=True, exist_ok=True)
    results = (
        *run_append_scenarios(
            arguments.binary,
            arguments.output / "append",
            seed=arguments.seed,
        ),
        *run_retirement_race_scenarios(
            arguments.binary,
            arguments.output / "retirement",
            seed=arguments.seed + 100,
            iterations=arguments.retirement_iterations,
        ),
        *run_replay_scenarios(
            arguments.binary,
            arguments.output / "replay",
            seed=arguments.seed + 200,
        ),
    )
    summary = {
        "scenarios": [
            {
                "history": str(result.history_path),
                "name": result.name,
                "status": result.check.status.value,
            }
            for result in results
        ],
        "seed": arguments.seed,
        "v": 1,
    }
    sys.stdout.buffer.write(canonical_json(summary) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

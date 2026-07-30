from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from verify.blackbox.scenarios import (
    run_append_scenarios,
    run_replay_scenarios,
    run_retirement_race_scenarios,
)


BINARY = Path(os.environ.get("GROUNDHOG_BIN", ""))


@unittest.skipUnless(BINARY.is_file(), "set GROUNDHOG_BIN to run external binary tests")
class ExternalBinaryTest(unittest.TestCase):
    def test_all_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            append = run_append_scenarios(BINARY, root / "append", seed=10)
            retirement = run_retirement_race_scenarios(
                BINARY, root / "retirement", seed=20, iterations=2
            )
            replay = run_replay_scenarios(BINARY, root / "replay", seed=30)
            self.assertEqual(len((*append, *retirement, *replay)), 9)


if __name__ == "__main__":
    unittest.main()

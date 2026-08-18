from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from verify.backend import BackendOptions
from verify.blackbox.transport import GroundhogProcess


class BackendOptionsTests(unittest.TestCase):
    def test_local_rejects_s3_values_and_s3_requires_unique_test_parent(self) -> None:
        with self.assertRaisesRegex(ValueError, "local backend"):
            BackendOptions("local", "bucket", None, None).validate()
        with self.assertRaisesRegex(ValueError, "requires bucket"):
            BackendOptions("s3").validate()
        with self.assertRaisesRegex(ValueError, "groundhog-tests"):
            BackendOptions("s3", "bucket", "us-west-2", "production").validate()

    def test_process_initialization_appends_a_unique_deployment_child(self) -> None:
        backend = BackendOptions(
            "s3", "company-groundhog", "us-west-2", "groundhog-tests/run-1"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "deployment-a"
            process = GroundhogProcess("groundhog", root=root, backend=backend)
            completed = MagicMock(returncode=0, stderr=b"")
            with patch("verify.blackbox.transport.subprocess.run", return_value=completed) as run:
                process.initialize()
        self.assertEqual(
            run.call_args.args[0],
            [
                str(Path("groundhog").resolve()),
                "init",
                str(root),
                "--backend",
                "s3",
                "--bucket",
                "company-groundhog",
                "--region",
                "us-west-2",
                "--prefix",
                "groundhog-tests/run-1/deployment-a",
            ],
        )


if __name__ == "__main__":
    unittest.main()

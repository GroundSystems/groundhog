from __future__ import annotations

import io
from pathlib import Path
import unittest
from unittest import mock

from verify.conformance.__main__ import main
from verify.conformance.validate import ContractError


class MainTests(unittest.TestCase):
    @mock.patch("verify.conformance.__main__.run_live")
    @mock.patch("verify.conformance.__main__.validate_document")
    @mock.patch("verify.conformance.__main__.load_document", return_value={})
    def test_default_runs_static_validation_only(
        self,
        load_document: mock.Mock,
        validate_document: mock.Mock,
        run_live: mock.Mock,
    ) -> None:
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertEqual(main([]), 0)
        load_document.assert_called_once_with(Path("openapi.yaml"))
        validate_document.assert_called_once_with({})
        run_live.assert_not_called()
        self.assertEqual(output.getvalue(), "validated openapi.yaml\n")

    @mock.patch("verify.conformance.__main__.run_live")
    @mock.patch("verify.conformance.__main__.validate_document")
    @mock.patch("verify.conformance.__main__.load_document", return_value={})
    def test_binary_runs_live_checks_with_deterministic_defaults(
        self,
        _load_document: mock.Mock,
        _validate_document: mock.Mock,
        run_live: mock.Mock,
    ) -> None:
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertEqual(main(["--binary", "groundhog"]), 0)
        run_live.assert_called_once_with(
            Path("groundhog"), Path("openapi.yaml"), None, 0
        )
        self.assertEqual(
            output.getvalue(), "validated groundhog against openapi.yaml\n"
        )

    @mock.patch(
        "verify.conformance.__main__.load_document",
        side_effect=ContractError("invalid contract"),
    )
    def test_contract_failure_has_stable_exit_status(self, _load_document: mock.Mock) -> None:
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertEqual(main([]), 1)
        self.assertEqual(output.getvalue(), "invalid contract\n")


if __name__ == "__main__":
    unittest.main()

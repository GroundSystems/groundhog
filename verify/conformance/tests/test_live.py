from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
from unittest import mock

from verify.conformance.live import (
    BlackboxAdapter,
    LiveError,
    RawResponse,
    build_request,
    parse_response,
    run,
)
from verify.backend import BackendOptions
from verify.conformance.validate import ContractError


class RawHttpTests(unittest.TestCase):
    def test_request_preserves_raw_duplicate_members(self) -> None:
        body = b'{"a":1,"a":2}'
        request = build_request("POST", "/v1/events", body, {"Content-Type": "application/json"})
        self.assertTrue(request.endswith(body))
        self.assertIn(b"Content-Length: 13\r\n", request)

    def test_chunked_response_decodes(self) -> None:
        response = parse_response(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"4\r\ntest\r\n3\r\ning\r\n0\r\n\r\n"
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"testing")

    def test_invalid_chunk_fails(self) -> None:
        with self.assertRaises(LiveError):
            parse_response(
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                b"4\r\nshort"
            )

    def test_duplicate_response_members_fail(self) -> None:
        response = RawResponse(200, {"content-type": "application/json"}, b'{"a":1,"a":2}')
        with self.assertRaisesRegex(LiveError, "duplicate member"):
            response.json()

    @mock.patch("verify.conformance.live.validate_document")
    @mock.patch("verify.conformance.live.load_document", return_value={})
    def test_live_run_validates_document_before_starting_server(
        self, _load_document: mock.Mock, validate_document: mock.Mock
    ) -> None:
        validate_document.side_effect = ContractError("invalid static contract")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "groundhog"
            binary.write_bytes(b"binary")
            with self.assertRaisesRegex(ContractError, "invalid static contract"):
                run(binary, Path("openapi.yaml"))
        validate_document.assert_called_once_with({})

    def test_blackbox_filter_excludes_streaming_and_invalid_operations(self) -> None:
        self.assertFalse(BlackboxAdapter._recordable("GET", "/v1/events?follow=true", b"", 200))
        self.assertFalse(BlackboxAdapter._recordable("GET", "/v1/events?limit=0", b"", 400))
        self.assertFalse(BlackboxAdapter._recordable("POST", "/v1/events", b"not-json", 400))
        self.assertTrue(
            BlackboxAdapter._recordable(
                "POST", "/v1/events", b'{"source":"s","batch_id":"b","events":[]}', 200
            )
        )

    def test_blackbox_filter_excludes_unmodeled_lineage_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = BlackboxAdapter(Path(directory) / "history.json", seed=0)
            request = build_request(
                "POST",
                "/v1/events",
                b'{"source":"new","batch_id":"lineage","events":[]}',
                {"Content-Type": "application/json"},
            )
            response = RawResponse(
                409,
                {"content-type": "application/json"},
                b'{"error":"source_lineage_conflict","message":"conflict"}',
            )
            adapter.record(request, response, 1, 2)
            self.assertEqual(adapter.recorder.history().operations, ())

    def test_query_live_mode_rejects_nonlocal_backend_before_start(self) -> None:
        backend = BackendOptions(
            "s3", "bucket", "us-west-2", "groundhog-tests/query-live"
        )
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "groundhog"
            binary.write_bytes(b"binary")
            with self.assertRaisesRegex(LiveError, "requires the local backend"):
                run(binary, Path("openapi.yaml"), backend=backend, query_enabled=True)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from verify.blackbox.history import (
    History,
    HistoryRecorder,
    OperationRecord,
    RequestRecord,
    ResponseRecord,
)


class HistoryTest(unittest.TestCase):
    def test_round_trip_is_canonical(self) -> None:
        operation = OperationRecord(
            seed=17,
            client_id="client",
            operation_id="operation",
            invoked_monotonic_ns=10,
            completed_monotonic_ns=20,
            request=RequestRecord("POST", "/v1/events", (), b"{}"),
            response=ResponseRecord(200, (("content-type", "application/json"),), b"{}"),
        )
        history = History(17, (operation,))
        encoded = history.to_bytes()
        self.assertEqual(History.from_bytes(encoded).to_bytes(), encoded)

    def test_recorder_persists_each_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            recorder = HistoryRecorder(path, 23)
            operation = OperationRecord(
                seed=23,
                client_id="client",
                operation_id="unknown",
                invoked_monotonic_ns=30,
                completed_monotonic_ns=40,
                request=RequestRecord("POST", "/v1/events", (), b"{}"),
                response=None,
                transport_error="connection reset",
                outcome_unknown=True,
            )
            recorder.append(operation)
            loaded = History.load(path)
            self.assertEqual(loaded.operations, (operation,))
            self.assertTrue(loaded.operations[0].is_inconclusive)


if __name__ == "__main__":
    unittest.main()

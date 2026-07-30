from __future__ import annotations

import unittest

from verify.blackbox.history import History, OperationRecord, RequestRecord, ResponseRecord, canonical_json
from verify.blackbox.linearizability import CheckStatus, check_history
from verify.blackbox.model import SequentialModel


def append_operation(
    operation_id: str,
    invoked: int,
    completed: int,
    batch_id: str,
    status: int,
    response: object,
) -> OperationRecord:
    request = {
        "v": 1,
        "batch_id": batch_id,
        "source": "source",
        "stream_precondition": {"stream": "stream", "expected_frontier": None},
        "events": [
            {
                "stream": "stream",
                "record_key": batch_id,
                "kind": "upserted",
                "payload": batch_id,
            }
        ],
    }
    if status == 200:
        response = dict(response)  # type: ignore[arg-type]
        response["batch_digest"] = SequentialModel._fingerprint(request)
    return OperationRecord(
        seed=1,
        client_id=operation_id,
        operation_id=operation_id,
        invoked_monotonic_ns=invoked,
        completed_monotonic_ns=completed,
        request=RequestRecord("POST", "/v1/events", (), canonical_json(request)),
        response=ResponseRecord(status, (), canonical_json(response)),
    )


class LinearizabilityTest(unittest.TestCase):
    def test_duplicate_resolves_a_lost_append_response(self) -> None:
        frontier = "00000000-0000-7000-8000-000000000001"
        retry = append_operation(
            "retry",
            3,
            4,
            "uncertain",
            200,
            {
                "status": "duplicate",
                "events": 1,
                "batch_digest": "replaced-by-helper",
                "first_event_id": frontier,
                "last_event_id": frontier,
            },
        )
        uncertain = OperationRecord(
            seed=1,
            client_id="uncertain",
            operation_id="uncertain",
            invoked_monotonic_ns=1,
            completed_monotonic_ns=2,
            request=retry.request,
            response=None,
            transport_error="response reset",
            outcome_unknown=True,
        )
        result = check_history(History(1, (uncertain, retry)))
        self.assertEqual(result.status, CheckStatus.LINEARIZABLE)
        self.assertEqual(result.linearization, ("uncertain", "retry"))
        bounded = check_history(History(1, (uncertain, retry)), max_states=1)
        self.assertEqual(bounded.status, CheckStatus.BOUND_EXCEEDED)

    def test_equal_timestamp_boundary_does_not_impose_order(self) -> None:
        frontier = "00000000-0000-7000-8000-000000000001"
        rejected = append_operation(
            "loser",
            1,
            2,
            "loser",
            409,
            {
                "error": "stream_frontier_conflict",
                "source": "source",
                "stream": "stream",
                "expected_frontier": None,
                "actual_frontier": frontier,
            },
        )
        committed = append_operation(
            "winner",
            2,
            3,
            "winner",
            200,
            {
                "status": "committed",
                "events": 1,
                "batch_digest": "digest",
                "first_event_id": frontier,
                "last_event_id": frontier,
            },
        )
        result = check_history(History(1, (rejected, committed)))
        self.assertEqual(result.status, CheckStatus.LINEARIZABLE)
        self.assertEqual(result.linearization, ("winner", "loser"))

    def test_concurrent_preconditions_have_one_serial_explanation(self) -> None:
        frontier = "00000000-0000-7000-8000-000000000001"
        committed = append_operation(
            "winner",
            1,
            10,
            "winner",
            200,
            {
                "status": "committed",
                "events": 1,
                "batch_digest": "digest",
                "first_event_id": frontier,
                "last_event_id": frontier,
            },
        )
        rejected = append_operation(
            "loser",
            2,
            9,
            "loser",
            409,
            {
                "error": "stream_frontier_conflict",
                "source": "source",
                "stream": "stream",
                "expected_frontier": None,
                "actual_frontier": frontier,
            },
        )
        result = check_history(History(1, (rejected, committed)))
        self.assertEqual(result.status, CheckStatus.LINEARIZABLE)
        self.assertEqual(result.linearization, ("winner", "loser"))

    def test_real_time_order_can_make_history_invalid(self) -> None:
        frontier = "00000000-0000-7000-8000-000000000001"
        rejected = append_operation(
            "loser",
            1,
            2,
            "loser",
            409,
            {
                "error": "stream_frontier_conflict",
                "source": "source",
                "stream": "stream",
                "expected_frontier": None,
                "actual_frontier": frontier,
            },
        )
        committed = append_operation(
            "winner",
            3,
            4,
            "winner",
            200,
            {
                "status": "committed",
                "events": 1,
                "batch_digest": "digest",
                "first_event_id": frontier,
                "last_event_id": frontier,
            },
        )
        result = check_history(History(1, (rejected, committed)))
        self.assertEqual(result.status, CheckStatus.NONLINEARIZABLE)

    def test_unknown_transport_outcome_is_inconclusive(self) -> None:
        operation = OperationRecord(
            seed=1,
            client_id="client",
            operation_id="unknown",
            invoked_monotonic_ns=1,
            completed_monotonic_ns=2,
            request=RequestRecord("POST", "/v1/events", (), b"{}"),
            response=None,
            transport_error="reset",
            outcome_unknown=True,
        )
        result = check_history(History(1, (operation,)))
        self.assertEqual(result.status, CheckStatus.INCONCLUSIVE)

    def test_malformed_unknown_request_does_not_use_duplicate_evidence(self) -> None:
        frontier = "00000000-0000-7000-8000-000000000001"
        retry = append_operation(
            "retry",
            3,
            4,
            "uncertain",
            200,
            {
                "status": "duplicate",
                "events": 1,
                "batch_digest": "replaced-by-helper",
                "first_event_id": frontier,
                "last_event_id": frontier,
            },
        )
        malformed = OperationRecord(
            seed=1,
            client_id="malformed",
            operation_id="malformed",
            invoked_monotonic_ns=1,
            completed_monotonic_ns=2,
            request=RequestRecord(
                "POST",
                "/v1/events",
                (),
                canonical_json({"source": "source", "batch_id": "uncertain"}),
            ),
            response=None,
            transport_error="response reset",
            outcome_unknown=True,
        )
        result = check_history(History(1, (malformed, retry)))
        self.assertEqual(result.status, CheckStatus.NONLINEARIZABLE)


if __name__ == "__main__":
    unittest.main()

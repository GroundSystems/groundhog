from __future__ import annotations

import unittest

from verify.blackbox.history import (
    OperationRecord,
    RequestRecord,
    ResponseRecord,
    canonical_json,
)
from verify.blackbox.model import ModelViolation, SequentialModel


def operation(
    operation_id: str,
    request_body: object,
    status: int,
    response_body: object,
    *,
    target: str = "/v1/events",
    response_headers: tuple[tuple[str, str], ...] = (),
    method: str = "POST",
) -> OperationRecord:
    return OperationRecord(
        seed=1,
        client_id="client",
        operation_id=operation_id,
        invoked_monotonic_ns=1,
        completed_monotonic_ns=2,
        request=RequestRecord(method, target, (), canonical_json(request_body)),
        response=ResponseRecord(status, response_headers, canonical_json(response_body)),
    )


def batch(payload: object = 1, expected: object = ...) -> dict[str, object]:
    value: dict[str, object] = {
        "v": 1,
        "batch_id": "batch",
        "source": "source",
        "events": [
            {
                "stream": "stream",
                "record_key": "key",
                "kind": "upserted",
                "payload": payload,
            }
        ],
    }
    if expected is not ...:
        value["stream_precondition"] = {
            "stream": "stream",
            "expected_frontier": expected,
        }
    return value


def committed_receipt(
    candidate: dict[str, object],
    *,
    first: str = "00000000-0000-7000-8000-000000000001",
    last: str | None = None,
) -> dict[str, object]:
    return {
        "status": "committed",
        "events": len(candidate["events"]),  # type: ignore[arg-type]
        "batch_digest": SequentialModel._fingerprint(candidate),
        "first_event_id": first,
        "last_event_id": last or first,
    }


class ModelTest(unittest.TestCase):
    def test_three_event_batch_has_atomic_replay_visibility(self) -> None:
        candidate = batch()
        candidate["events"] = [
            {
                "stream": "stream",
                "record_key": f"key-{index}",
                "kind": "upserted",
                "payload": {"index": index},
            }
            for index in range(3)
        ]
        first = "00000000-0000-7000-8000-000000000001"
        middle = "00000000-0000-7000-8000-000000000002"
        last = "00000000-0000-7000-8000-000000000003"
        receipt = committed_receipt(candidate, first=first, last=last)
        model = SequentialModel()
        model.apply(operation("append-three", candidate, 200, receipt))
        replay_events = [
            {
                "event_id": event_id,
                "batch_id": "batch",
                "source": "source",
                **event,
            }
            for event_id, event in zip(
                (first, middle, last),
                candidate["events"],  # type: ignore[arg-type]
            )
        ]
        replay = {
            "events": replay_events,
            "last_event_id": last,
            "next_after": last,
            "snapshot_through_event_id": last,
        }
        model.apply(
            operation(
                "replay-three",
                {},
                200,
                replay,
                method="GET",
                target="/v1/events?limit=10",
            )
        )

        truncated = SequentialModel()
        truncated.apply(operation("append-three", candidate, 200, receipt))
        first_page = {
            "events": [replay_events[0]],
            "last_event_id": first,
            "next_after": first,
            "snapshot_through_event_id": last,
        }
        truncated.apply(
            operation(
                "replay-byte-limited",
                {},
                200,
                first_page,
                method="GET",
                target="/v1/events?limit=10",
            )
        )
        resumed = {
            "events": replay_events[1:],
            "last_event_id": last,
            "next_after": last,
            "snapshot_through_event_id": last,
        }
        truncated.apply(
            operation(
                "replay-resumed",
                {},
                200,
                resumed,
                method="GET",
                target=f"/v1/events?after={first}&limit=10",
            )
        )

        incomplete = SequentialModel()
        incomplete.apply(operation("append-three", candidate, 200, receipt))
        missing_middle = dict(replay)
        missing_middle["events"] = [replay_events[0], replay_events[2]]
        with self.assertRaises(ModelViolation):
            incomplete.apply(
                operation(
                    "replay-incomplete",
                    {},
                    200,
                    missing_middle,
                    method="GET",
                    target="/v1/events?limit=10",
                )
            )

    def test_batch_id_identity_is_scoped_to_source(self) -> None:
        first = batch()
        first["source"] = "first-source"
        second = batch()
        second["source"] = "second-source"
        model = SequentialModel()
        model.apply(operation("first", first, 200, committed_receipt(first)))
        model.apply(
            operation(
                "second",
                second,
                200,
                committed_receipt(
                    second,
                    first="00000000-0000-7000-8000-000000000002",
                ),
            )
        )
        self.assertEqual(
            set(model.batches),
            {("first-source", "batch"), ("second-source", "batch")},
        )

    def test_commit_validates_batch_digest_and_event_bounds(self) -> None:
        candidate = batch()
        self.assertEqual(
            SequentialModel._fingerprint(candidate),
            "f2f766e2c9baa046927f9af5d77685f3e54be212175f40cbff12342d8e272ec4",
        )
        wrong_digest = committed_receipt(candidate)
        wrong_digest["batch_digest"] = "0" * 64
        with self.assertRaises(ModelViolation):
            SequentialModel().apply(
                operation("wrong-digest", candidate, 200, wrong_digest)
            )

        wrong_bounds = committed_receipt(
            candidate,
            last="00000000-0000-7000-8000-000000000002",
        )
        with self.assertRaises(ModelViolation):
            SequentialModel().apply(
                operation("wrong-bounds", candidate, 200, wrong_bounds)
            )

        malformed = committed_receipt(candidate)
        malformed["first_event_id"] = "not-a-uuid"
        with self.assertRaises(ModelViolation):
            SequentialModel().apply(
                operation("malformed-bound", candidate, 200, malformed)
            )

    def test_overload_is_a_definite_no_op(self) -> None:
        model = SequentialModel()
        candidate = batch()
        model.apply(
            operation(
                "overloaded",
                candidate,
                429,
                {"error": "overloaded"},
                response_headers=(("retry-after", "1"),),
            )
        )
        receipt = committed_receipt(candidate)
        model.apply(operation("commit-after-overload", candidate, 200, receipt))

    def test_overload_requires_the_contract_shape(self) -> None:
        model = SequentialModel()
        with self.assertRaises(ModelViolation):
            model.apply(
                operation(
                    "wrong-code",
                    batch(),
                    429,
                    {"error": "busy"},
                    response_headers=(("retry-after", "1"),),
                )
            )
        with self.assertRaises(ModelViolation):
            model.apply(
                operation("missing-retry-after", batch(), 429, {"error": "overloaded"})
            )

    def test_retry_precedes_stale_precondition_and_retirement(self) -> None:
        model = SequentialModel()
        accepted = batch(expected=None)
        receipt = committed_receipt(accepted)
        model.apply(operation("commit", accepted, 200, receipt))
        retirement = {
            "v": 1,
            "status": "retired",
            "source": "source",
            "final_frontier": receipt["last_event_id"],
            "retirement_event_id": "00000000-0000-7000-8000-000000000002",
        }
        model.apply(
            operation(
                "retire",
                {"v": 1, "source": "source"},
                200,
                retirement,
                target="/v1/sources/retire",
            )
        )
        duplicate = dict(receipt)
        duplicate["status"] = "duplicate"
        model.apply(operation("retry", accepted, 200, duplicate))

    def test_changed_identity_conflicts_before_retirement(self) -> None:
        model = SequentialModel()
        candidate = batch()
        receipt = committed_receipt(candidate)
        model.apply(operation("commit", candidate, 200, receipt))
        model.apply(
            operation(
                "retire",
                {"v": 1, "source": "source"},
                200,
                {
                    "v": 1,
                    "status": "retired",
                    "source": "source",
                    "final_frontier": receipt["last_event_id"],
                    "retirement_event_id": "00000000-0000-7000-8000-000000000002",
                },
                target="/v1/sources/retire",
            )
        )
        model.apply(
            operation(
                "conflict",
                batch(payload=2),
                409,
                {"error": "batch_id already committed with different content"},
            )
        )

    def test_changed_identity_accepts_target_error_body(self) -> None:
        model = SequentialModel()
        candidate = batch()
        receipt = committed_receipt(candidate)
        model.apply(operation("commit", candidate, 200, receipt))
        model.apply(
            operation(
                "conflict",
                batch(payload=2),
                409,
                {
                    "error": "batch_id_conflict",
                    "message": "The batch identity has different content.",
                },
            )
        )

    def test_wrong_conflict_order_is_rejected(self) -> None:
        model = SequentialModel()
        with self.assertRaises(ModelViolation):
            model.apply(
                operation(
                    "unexpected",
                    batch(expected=None),
                    409,
                    {
                        "error": "stream_frontier_conflict",
                        "source": "source",
                        "stream": "stream",
                        "expected_frontier": None,
                        "actual_frontier": None,
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()

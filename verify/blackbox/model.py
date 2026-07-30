"""Sequential durable-state model for the Groundhog HTTP contract."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import math
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit
import uuid

from .history import OperationRecord


class ModelViolation(ValueError):
    """An operation response cannot occur in the current model state."""


def _ecmascript_number(value: float) -> str:
    if not math.isfinite(value):
        raise ModelViolation("payload contains a non-finite number")
    if value == 0.0:
        return "0"
    sign = "-" if value < 0.0 else ""
    shortest = repr(abs(value)).lower()
    if "e" in shortest:
        mantissa, exponent_text = shortest.split("e")
        exponent = int(exponent_text)
    else:
        mantissa, exponent = shortest, 0
    if "." in mantissa:
        before, after = mantissa.split(".")
    else:
        before, after = mantissa, ""
    digits = before + after
    decimal_point = len(before) + exponent
    while len(digits) > 1 and digits[0] == "0":
        digits = digits[1:]
        decimal_point -= 1
    while len(digits) > 1 and digits[-1] == "0":
        digits = digits[:-1]
    count = len(digits)
    if count <= decimal_point <= 21:
        body = digits + ("0" * (decimal_point - count))
    elif 0 < decimal_point <= 21:
        body = digits[:decimal_point] + "." + digits[decimal_point:]
    elif -6 < decimal_point <= 0:
        body = "0." + ("0" * -decimal_point) + digits
    else:
        body = digits[0]
        if count > 1:
            body += "." + digits[1:]
        scientific_exponent = decimal_point - 1
        exponent_sign = "+" if scientific_exponent >= 0 else "-"
        body += f"e{exponent_sign}{abs(scientific_exponent)}"
    return sign + body


def _jcs_string(value: str) -> str:
    output = ['"']
    short_escapes = {
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
        '"': '\\"',
        "\\": "\\\\",
    }
    for character in value:
        codepoint = ord(character)
        if character in short_escapes:
            output.append(short_escapes[character])
        elif codepoint < 0x20:
            output.append(f"\\u{codepoint:04x}")
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ModelViolation("payload contains malformed Unicode")
        else:
            output.append(character)
    output.append('"')
    return "".join(output)


def _jcs(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _ecmascript_number(float(value))
    if isinstance(value, str):
        return _jcs_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_jcs(child) for child in value) + "]"
    if isinstance(value, dict):
        members = sorted(value.items(), key=lambda member: member[0].encode("utf-16-be"))
        return "{" + ",".join(
            _jcs_string(str(key)) + ":" + _jcs(child) for key, child in members
        ) + "}"
    raise ModelViolation(f"payload contains an unsupported value: {type(value)!r}")


@dataclass(frozen=True)
class BatchState:
    fingerprint: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True)
class RetirementState:
    final_frontier: str
    retirement_event_id: str


@dataclass
class EventFact:
    event_id: str | None
    batch_id: str
    source: str
    stream: str
    record_key: str
    kind: str
    payload: Any
    occurred_at: Any = None

    def expected_members(self) -> dict[str, Any]:
        value = {
            "batch_id": self.batch_id,
            "source": self.source,
            "stream": self.stream,
            "record_key": self.record_key,
            "kind": self.kind,
            "payload": self.payload,
        }
        if self.event_id is not None:
            value["event_id"] = self.event_id
        if self.occurred_at is not None:
            value["occurred_at"] = self.occurred_at
        return value


class SequentialModel:
    """Model append, retirement, replay, and stream enumeration state."""

    def __init__(self) -> None:
        self.batches: dict[tuple[str, str], BatchState] = {}
        self.source_frontiers: dict[str, str] = {}
        self.stream_frontiers: dict[tuple[str, str], str | None] = {}
        self.retired: dict[str, RetirementState] = {}
        self.chain: list[EventFact] = []
        self.global_frontier: str | None = None

    def clone(self) -> SequentialModel:
        return copy.deepcopy(self)

    def apply(self, operation: OperationRecord) -> None:
        if operation.response is None:
            if operation.outcome_unknown:
                raise ModelViolation("transport outcome is inconclusive")
            return
        method = operation.request.method.upper()
        path = urlsplit(operation.request.target).path
        if method == "POST" and path == "/v1/events":
            self._append(operation)
        elif method == "POST" and path == "/v1/sources/retire":
            self._retire(operation)
        elif method == "GET" and path == "/v1/events":
            self._replay(operation)
        elif method == "GET" and path == "/v1/streams":
            self._streams(operation)
        else:
            raise ModelViolation(f"operation is outside the verifier model: {method} {path}")

    @staticmethod
    def _body(operation: OperationRecord) -> Any:
        assert operation.response is not None
        try:
            return operation.response.json_body()
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelViolation(f"response body is not JSON: {error}") from error

    @staticmethod
    def _request_body(operation: OperationRecord) -> Any:
        try:
            return operation.request.json_body()
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelViolation(f"request body is not JSON: {error}") from error

    @staticmethod
    def _fingerprint(batch: Mapping[str, Any]) -> str:
        events = []
        for event in batch["events"]:
            commitment = {
                "content_hash": hashlib.sha256(
                    _jcs(event["payload"]).encode("utf-8")
                ).hexdigest(),
                "kind": event["kind"],
                "record_key": event["record_key"],
                "stream": event["stream"],
            }
            if "occurred_at" in event:
                commitment["occurred_at"] = event["occurred_at"]
            events.append(commitment)
        identity = {"events": events, "source": batch["source"], "v": 1}
        return hashlib.sha256(_jcs(identity).encode("utf-8")).hexdigest()

    @staticmethod
    def _event_id(value: Any, member: str) -> uuid.UUID:
        if not isinstance(value, str):
            raise ModelViolation(f"commit receipt lacks {member}")
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError) as error:
            raise ModelViolation(f"commit receipt has an invalid {member}") from error
        if str(parsed) != value or parsed.version != 7 or parsed.variant != uuid.RFC_4122:
            raise ModelViolation(f"commit receipt has an invalid {member}")
        return parsed

    @staticmethod
    def _require_members(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                raise ModelViolation(
                    f"response member {key!r} is {actual.get(key)!r}, expected {expected_value!r}"
                )

    @staticmethod
    def _require_status(operation: OperationRecord, expected: int) -> Mapping[str, Any]:
        assert operation.response is not None
        if operation.response.status != expected:
            raise ModelViolation(
                f"status is {operation.response.status}, expected {expected}"
            )
        body = SequentialModel._body(operation)
        if not isinstance(body, dict):
            raise ModelViolation("response JSON is not an object")
        return body

    @staticmethod
    def _require_overloaded(operation: OperationRecord) -> None:
        assert operation.response is not None
        body = SequentialModel._require_status(operation, 429)
        if body.get("error") != "overloaded":
            raise ModelViolation("429 response lacks the overloaded error code")
        retry_after = [
            value
            for key, value in operation.response.headers
            if key.lower() == "retry-after"
        ]
        if len(retry_after) != 1:
            raise ModelViolation("429 response must contain one Retry-After header")
        try:
            delay = int(retry_after[0])
        except ValueError as error:
            raise ModelViolation("429 Retry-After is not an integer") from error
        if delay < 1:
            raise ModelViolation("429 Retry-After must be positive")

    def _append(self, operation: OperationRecord) -> None:
        assert operation.response is not None
        if operation.response.status == 429:
            self._require_overloaded(operation)
            return
        batch = self._request_body(operation)
        if not isinstance(batch, dict):
            raise ModelViolation("append request is not an object")
        source = str(batch["source"])
        batch_id = str(batch["batch_id"])
        key = (source, batch_id)
        fingerprint = self._fingerprint(batch)
        existing = self.batches.get(key)

        if existing is not None:
            if existing.fingerprint == fingerprint:
                body = self._require_status(operation, 200)
                self._require_members(body, {"status": "duplicate"})
                for receipt_key in (
                    "batch_digest",
                    "events",
                    "first_event_id",
                    "last_event_id",
                ):
                    if body.get(receipt_key) != existing.receipt.get(receipt_key):
                        raise ModelViolation(f"duplicate changed receipt member {receipt_key!r}")
                return
            body = self._require_status(operation, 409)
            if not isinstance(body.get("error"), str):
                raise ModelViolation("batch conflict response lacks an error code")
            return

        retirement = self.retired.get(source)
        if retirement is not None:
            body = self._require_status(operation, 409)
            self._require_members(
                body,
                {
                    "source": source,
                    "final_frontier": retirement.final_frontier,
                    "retirement_event_id": retirement.retirement_event_id,
                },
            )
            return

        precondition = batch.get("stream_precondition")
        if precondition is not None:
            stream = str(precondition["stream"])
            expected = precondition.get("expected_frontier")
            actual = self.stream_frontiers.get((source, stream))
            if actual is not None and actual.startswith("@unknown:"):
                raise ModelViolation("the model cannot resolve an interior stream frontier")
            if expected != actual:
                body = self._require_status(operation, 409)
                self._require_members(
                body,
                {
                    "source": source,
                        "stream": stream,
                        "expected_frontier": expected,
                        "actual_frontier": actual,
                    },
                )
                return

        body = self._require_status(operation, 200)
        self._require_members(body, {"status": "committed", "events": len(batch["events"])})
        first = body.get("first_event_id")
        last = body.get("last_event_id")
        first_id = self._event_id(first, "first_event_id")
        last_id = self._event_id(last, "last_event_id")
        if body.get("batch_digest") != fingerprint:
            raise ModelViolation("commit receipt batch_digest does not match the request")
        if first > last:
            raise ModelViolation("commit receipt event ID bounds are reversed")
        if len(batch["events"]) == 1 and first_id != last_id:
            raise ModelViolation("single-event receipt has different event ID bounds")
        if len(batch["events"]) > 1 and first_id >= last_id:
            raise ModelViolation("multi-event receipt does not advance its event ID bounds")
        if self.global_frontier is not None and first <= self.global_frontier:
            raise ModelViolation("committed event IDs do not advance the chain")
        events = batch["events"]
        for index, event in enumerate(events):
            if index == 0:
                event_id: str | None = first
            elif index == len(events) - 1:
                event_id = last
            else:
                event_id = None
            fact = EventFact(
                event_id=event_id,
                batch_id=batch_id,
                source=source,
                stream=str(event["stream"]),
                record_key=str(event["record_key"]),
                kind=str(event["kind"]),
                payload=event["payload"],
                occurred_at=event.get("occurred_at"),
            )
            self.chain.append(fact)
            marker = event_id or f"@unknown:{operation.operation_id}:{index}"
            self.stream_frontiers[(source, fact.stream)] = marker
        self.source_frontiers[source] = last
        self.global_frontier = last
        self.batches[key] = BatchState(fingerprint=fingerprint, receipt=dict(body))

    def _retire(self, operation: OperationRecord) -> None:
        assert operation.response is not None
        if operation.response.status == 429:
            self._require_overloaded(operation)
            return
        request = self._request_body(operation)
        source = str(request["source"])
        existing = self.retired.get(source)
        if existing is not None:
            body = self._require_status(operation, 200)
            self._require_members(
                body,
                {
                    "v": 1,
                    "status": "already_retired",
                    "source": source,
                    "final_frontier": existing.final_frontier,
                    "retirement_event_id": existing.retirement_event_id,
                },
            )
            return
        final = self.source_frontiers.get(source)
        if final is None:
            body = self._require_status(operation, 404)
            self._require_members(body, {"source": source})
            return
        body = self._require_status(operation, 200)
        retirement_id = body.get("retirement_event_id")
        if not isinstance(retirement_id, str):
            raise ModelViolation("retirement response lacks retirement_event_id")
        self._require_members(
            body,
            {
                "v": 1,
                "status": "retired",
                "source": source,
                "final_frontier": final,
            },
        )
        if self.global_frontier is not None and retirement_id <= self.global_frontier:
            raise ModelViolation("retirement event does not advance the chain")
        self.retired[source] = RetirementState(final, retirement_id)
        batch_id = f"groundhog/retire/{source}/{final}"
        self.chain.append(
            EventFact(
                event_id=retirement_id,
                batch_id=batch_id,
                source="system",
                stream="groundhog.source_lifecycle",
                record_key=source,
                kind="source_retired",
                payload={"v": 1, "source": source, "final_frontier": final},
            )
        )
        self.source_frontiers["system"] = retirement_id
        self.stream_frontiers[("system", "groundhog.source_lifecycle")] = retirement_id
        self.global_frontier = retirement_id

    def _replay(self, operation: OperationRecord) -> None:
        body = self._require_status(operation, 200)
        query = self._query(operation)
        after = query.get("after", [None])[0]
        limit = int(query.get("limit", [1000])[0])
        filters = {
            name: query[name][0]
            for name in ("source", "stream", "record_key", "kind")
            if name in query
        }
        after_index = None
        if after is not None:
            after_index = next(
                (
                    index
                    for index, event in enumerate(self.chain)
                    if event.event_id == after
                ),
                None,
            )
            if after_index is None:
                if self.global_frontier is None or after < self.global_frontier:
                    raise ModelViolation("replay cursor is absent from the modeled chain")
                after_index = len(self.chain) - 1
        candidates = []
        for index, event in enumerate(self.chain):
            if after_index is not None and index <= after_index:
                continue
            if any(getattr(event, name) != value for name, value in filters.items()):
                continue
            candidates.append(event)
        actual_events = body.get("events")
        if not isinstance(actual_events, list):
            raise ModelViolation("replay events is not an array")
        maximum = min(limit, len(candidates))
        if len(actual_events) > maximum:
            raise ModelViolation("replay event count does not match the model")
        if candidates and not actual_events:
            raise ModelViolation("non-empty replay made no progress")
        returned = candidates[: len(actual_events)]
        previous_id = after
        for actual, expected in zip(actual_events, returned):
            if not isinstance(actual, dict):
                raise ModelViolation("replay event is not an object")
            self._require_members(actual, expected.expected_members())
            event_id = actual.get("event_id")
            parsed = self._event_id(event_id, "replay event_id")
            if previous_id is not None and str(parsed) <= previous_id:
                raise ModelViolation("replay event IDs are not increasing")
            if expected.event_id is None:
                expected.event_id = str(parsed)
            elif expected.event_id != str(parsed):
                raise ModelViolation("replay event ID does not match the model")
            previous_id = str(parsed)
        expected_last = returned[-1].event_id if returned else None
        if expected_last is None:
            if "last_event_id" in body:
                raise ModelViolation("empty replay includes last_event_id")
        elif body.get("last_event_id") != expected_last:
            raise ModelViolation("replay last_event_id does not match the last event")
        next_after = body.get("next_after")
        if returned and (len(returned) == limit or len(returned) < len(candidates)):
            allowed_next = {returned[-1].event_id}
        elif returned:
            allowed_next = {returned[-1].event_id, self.global_frontier}
        elif self.global_frontier is not None:
            allowed_next = {
                max(after, self.global_frontier)
                if after is not None
                else self.global_frontier
            }
        else:
            allowed_next = {after}
        if next_after not in allowed_next:
            raise ModelViolation("replay next_after does not match its scan progress")
        self._require_members(
            body, {"snapshot_through_event_id": self.global_frontier}
        )

    def _streams(self, operation: OperationRecord) -> None:
        body = self._require_status(operation, 200)
        query = self._query(operation)
        through = query.get("through", [self.global_frontier])[0]
        limit = int(query.get("limit", [100])[0])
        after = query.get("after", [None])[0]
        source_filter = query.get("source", [None])[0]
        if through is not None and not any(event.event_id == through for event in self.chain):
            raise ModelViolation("stream anchor is absent from the modeled chain")
        summaries: dict[tuple[str, str], tuple[str, int]] = {}
        for event in self.chain:
            if event.event_id is None:
                raise ModelViolation("the model cannot enumerate an interior event ID")
            if through is not None and event.event_id > through:
                break
            if source_filter is not None and event.source != source_filter:
                if event.event_id == through:
                    break
                continue
            key = (event.source, event.stream)
            _, count = summaries.get(key, (event.event_id, 0))
            summaries[key] = (event.event_id, count + 1)
            if event.event_id == through:
                break
        rows = []
        for key in sorted(summaries):
            cursor = f"{key[0]}/{key[1]}"
            if after is not None and cursor <= after:
                continue
            frontier, count = summaries[key]
            rows.append(
                {
                    "source": key[0],
                    "stream": key[1],
                    "frontier_event_id": frontier,
                    "event_count": count,
                }
            )
        has_more = len(rows) > limit
        expected_rows = rows[:limit]
        expected_next = (
            f"{expected_rows[-1]['source']}/{expected_rows[-1]['stream']}"
            if has_more
            else None
        )
        self._require_members(
            body,
            {
                "v": 1,
                "streams": expected_rows,
                "next_after": expected_next,
                "snapshot_through_event_id": through,
            },
        )

    @staticmethod
    def _query(operation: OperationRecord) -> dict[str, list[str]]:
        return parse_qs(urlsplit(operation.request.target).query, keep_blank_values=True)

#!/usr/bin/env python3
"""Independent, standard-library verifier for the stable-format compatibility vectors.

This program intentionally imports no Groundhog or Rust code.  It parses JSON with
duplicate preservation, applies the event-format I-JSON screens, serializes RFC 8785
JCS (including ECMAScript's binary64 formatting), and recomputes every textual/hash
commitment in this directory.  The Parquet file is opaque here: its whole-file hash is
verified, while Rust's vector test independently checks its schema and logical rows.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MAX_SAFE_INTEGER = 9_007_199_254_740_991


class VectorFailure(Exception):
    """A failed vector assertion or an expected admission-screen reason."""


class ObjectPairs(list[tuple[str, Any]]):
    """A JSON object whose source members have not been collapsed into a map."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VectorFailure(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ecmascript_number(value: float) -> str:
    """ECMAScript Number::toString spelling used by RFC 8785.

    CPython's repr supplies the shortest round-tripping significand.  The remainder
    applies ECMAScript's fixed/scientific thresholds and exponent syntax.  jcs.json's
    official Appendix B bit-pattern corpus validates this independent implementation.
    """

    if not math.isfinite(value):
        raise VectorFailure("non-finite")
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


def parse_integer(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise VectorFailure("non-finite")
    if abs(int(token)) > MAX_SAFE_INTEGER and ecmascript_number(value) != token:
        raise VectorFailure("integer-out-of-range")
    return value


def parse_decimal(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise VectorFailure("non-finite")
    return value


def reject_constant(_token: str) -> None:
    raise VectorFailure("non-finite")


def preserve_object(pairs: list[tuple[str, Any]]) -> ObjectPairs:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise VectorFailure("duplicate-key")
        seen.add(key)
    return ObjectPairs(pairs)


def screen_unicode(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise VectorFailure("malformed-unicode")
    elif isinstance(value, ObjectPairs):
        for key, child in value:
            screen_unicode(key)
            screen_unicode(child)
    elif isinstance(value, list):
        for child in value:
            screen_unicode(child)


def parse_json(text: str) -> Any:
    try:
        value = json.loads(
            text,
            parse_int=parse_integer,
            parse_float=parse_decimal,
            parse_constant=reject_constant,
            object_pairs_hook=preserve_object,
        )
    except json.JSONDecodeError as error:
        raise VectorFailure("not-json") from error
    screen_unicode(value)
    return value


def screen_payload_nesting(value: Any, maximum: int, containers: int = 0) -> None:
    if isinstance(value, ObjectPairs):
        next_depth = containers + 1
        if next_depth > maximum:
            raise VectorFailure("nesting-too-deep")
        for _key, child in value:
            screen_payload_nesting(child, maximum, next_depth)
    elif isinstance(value, list):
        next_depth = containers + 1
        if next_depth > maximum:
            raise VectorFailure("nesting-too-deep")
        for child in value:
            screen_payload_nesting(child, maximum, next_depth)


def parse_payload(text: str, maximum: int = 128) -> Any:
    value = parse_json(text)
    screen_payload_nesting(value, maximum)
    return value


def jcs_string(value: str) -> str:
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
            raise VectorFailure("malformed-unicode")
        else:
            output.append(character)
    output.append('"')
    return "".join(output)


def utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def jcs(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return ecmascript_number(float(value))
    if isinstance(value, str):
        return jcs_string(value)
    if isinstance(value, ObjectPairs):
        members = sorted(value, key=lambda member: utf16_key(member[0]))
        return "{" + ",".join(
            jcs_string(key) + ":" + jcs(child) for key, child in members
        ) + "}"
    if isinstance(value, dict):
        members = sorted(value.items(), key=lambda member: utf16_key(member[0]))
        return "{" + ",".join(
            jcs_string(key) + ":" + jcs(child) for key, child in members
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(jcs(child) for child in value) + "]"
    raise TypeError(f"unsupported JCS value: {type(value)!r}")


def load_json(name: str) -> Any:
    with (HERE / name).open(encoding="utf-8") as source:
        return json.load(source)


def read_text(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


def verify_jcs() -> None:
    vectors = load_json("jcs.json")
    for case in vectors["canonical"]:
        actual = jcs(parse_json(case["input"]))
        require(actual == case["jcs"], f"jcs canonical case {case['name']}")
        require(jcs(parse_json(actual)) == actual, f"jcs closure case {case['name']}")

    for case in vectors["ieee754"]:
        value = struct.unpack(">d", bytes.fromhex(case["bits"]))[0]
        require(
            ecmascript_number(value) == case["jcs"],
            f"RFC 8785 Appendix B bits {case['bits']}",
        )

    for case in vectors["rejects"]:
        try:
            parse_json(case["input"])
        except VectorFailure as error:
            require(str(error) == case["reason"], f"reject reason {case['name']}")
        else:
            raise VectorFailure(f"reject case was admitted: {case['name']}")

    maximum = vectors["limits"]["max_payload_nesting"]
    accepted = ("[" * maximum) + "0" + ("]" * maximum)
    refused = ("[" * (maximum + 1)) + "0" + ("]" * (maximum + 1))
    parse_payload(accepted, maximum)
    try:
        parse_payload(refused, maximum)
    except VectorFailure as error:
        require(str(error) == "nesting-too-deep", "payload nesting refusal reason")
    else:
        raise VectorFailure("payload nesting maximum + 1 was admitted")


def verify_content_hashes() -> None:
    vector = load_json("content_hash.json")
    canonical = jcs(parse_payload(vector["payload_input"]))
    require(canonical == vector["canonical"], "ASCII payload canonical bytes")
    require(sha256(canonical.encode()) == vector["content_hash"], "ASCII content_hash")

    unicode_vector = vector["unicode"]
    canonical = jcs(parse_payload(unicode_vector["payload_input"]))
    canonical_bytes = canonical.encode("utf-8")
    require(canonical == unicode_vector["canonical"], "Unicode payload canonical text")
    require(canonical_bytes.hex() == unicode_vector["canonical_utf8_hex"], "Unicode UTF-8 bytes")
    require(sha256(canonical_bytes) == unicode_vector["content_hash"], "Unicode content_hash")


def recompute_events() -> list[dict[str, Any]]:
    vector = load_json("envelope.json")
    events: list[dict[str, Any]] = []
    for source_event in vector["events"]:
        payload = parse_payload(source_event["payload_input"])
        payload_canonical = jcs(payload)
        content_hash = sha256(payload_canonical.encode())
        require(payload_canonical == source_event["payload_canonical"], "event payload canonical")
        require(content_hash == source_event["content_hash"], "event content_hash")

        envelope = {
            "event_id": source_event["event_id"],
            "source": vector["source"],
            "stream": source_event["stream"],
            "record_key": source_event["record_key"],
            "kind": source_event["kind"],
            "observed_at": vector["observed_at"],
            "content_hash": content_hash,
            "batch_id": vector["batch_id"],
        }
        if source_event["occurred_at"] is not None:
            envelope["occurred_at"] = source_event["occurred_at"]
        canonical_envelope = jcs(envelope)
        event_hash = sha256(canonical_envelope.encode())
        require(canonical_envelope == source_event["canonical_envelope"], "canonical envelope")
        require(event_hash == source_event["event_hash"], "event_hash")
        events.append(
            {
                **envelope,
                "payload": payload,
                "payload_canonical": payload_canonical,
                "event_hash": event_hash,
            }
        )
    return events


def verify_batch(events: list[dict[str, Any]]) -> str:
    vector = load_json("batch_digest.json")
    descriptors: list[dict[str, Any]] = []
    for expected, event in zip(vector["descriptors"], events, strict=True):
        descriptor = {
            "stream": event["stream"],
            "record_key": event["record_key"],
            "kind": event["kind"],
            "content_hash": event["content_hash"],
        }
        if "occurred_at" in event:
            descriptor["occurred_at"] = event["occurred_at"]
        require(descriptor == expected, "batch descriptor")
        descriptors.append(descriptor)
    preimage = jcs({"v": 1, "source": vector["source"], "events": descriptors})
    digest = sha256(preimage.encode())
    require(preimage == vector["digest_preimage"], "batch digest preimage")
    require(digest == vector["batch_digest"], "batch_digest")
    return digest


def verify_chain(events: list[dict[str, Any]]) -> str:
    vector = load_json("chain.json")
    head = hashlib.sha256(vector["genesis_preimage"].encode("ascii")).digest()
    require(head.hex() == vector["genesis_head"], "genesis head")
    require([event["event_hash"] for event in events] == vector["event_hashes"], "chain leaves")
    for leaf, expected in zip(vector["event_hashes"], vector["heads"], strict=True):
        head = hashlib.sha256(head + bytes.fromhex(leaf)).digest()
        require(head.hex() == expected, "chain fold")
    return head.hex()


def verify_storage_records(events: list[dict[str, Any]], digest: str, head: str) -> None:
    format_record = {
        "type": "format",
        "format_id": "groundhog/log",
        "schema_version": 1,
        "min_reader": 1,
        "min_writer": 1,
        "stability": "stable",
    }
    require(jcs(format_record) + "\n" == read_text("format_record.txt"), "format record bytes")

    tail_lines = []
    for event in events:
        line = {
            key: value
            for key, value in event.items()
            if key not in {"payload_canonical"}
        }
        line["batch_len"] = len(events)
        line["batch_digest"] = digest
        tail_lines.append(jcs(line))
    expected_tail = "\n".join(tail_lines) + "\n"
    require(expected_tail == read_text("tail_one_batch.ndjson"), "tail fixture bytes")

    segment = load_json("segment_expected.json")
    segment_bytes = (HERE / "segment.parquet").read_bytes()
    segment_hash = sha256(segment_bytes)
    segment_path = (
        f"segments/{events[0]['event_id']}_{events[-1]['event_id']}_{segment_hash}.parquet"
    )
    require(segment_hash == segment["sha256"], "segment whole-file SHA-256")
    require(segment_path == segment["path"], "content-addressed segment path")
    require(segment["events"] == len(events), "segment event count")
    require(segment["first_event_id"] == events[0]["event_id"], "segment first event_id")
    require(segment["last_event_id"] == events[-1]["event_id"], "segment last event_id")
    require(segment["head"] == head, "segment chain head")
    require(segment_hash in segment_path, "segment path commits its SHA-256")

    rows = []
    for event in events:
        row = {
            key: value
            for key, value in event.items()
            if key not in {"payload", "payload_canonical"}
        }
        row["payload"] = event["payload_canonical"]
        if "occurred_at" not in row:
            row["occurred_at"] = None
        rows.append(row)
    require(rows == segment["rows"], "segment expected logical rows")

    batch = {
        "source": events[0]["source"],
        "batch_id": events[0]["batch_id"],
        "batch_digest": digest,
        "events": len(events),
        "first_event_id": events[0]["event_id"],
        "last_event_id": events[-1]["event_id"],
    }
    require(segment["batches"] == [batch], "segment batch partition")
    seal_record = {
        "type": "segment",
        "schema_version": 1,
        "path": segment_path,
        "sha256": segment_hash,
        "first_event_id": segment["first_event_id"],
        "last_event_id": segment["last_event_id"],
        "events": segment["events"],
        "batches": [batch],
        "head": head,
        "sealed_at": "2026-07-10T00:00:00.000Z",
    }
    require(jcs(seal_record) + "\n" == read_text("seal_manifest_record.txt"), "seal record bytes")


def verify_lifecycle() -> None:
    vector = load_json("lifecycle.json")
    events: list[dict[str, Any]] = []
    for source_event in vector["events"]:
        payload = parse_payload(source_event["payload_input"])
        payload_canonical = jcs(payload)
        content_hash = sha256(payload_canonical.encode())
        require(
            payload_canonical == source_event["payload_canonical"],
            f"lifecycle {source_event['role']} payload bytes",
        )
        require(
            content_hash == source_event["content_hash"],
            f"lifecycle {source_event['role']} content_hash",
        )
        envelope = {
            "event_id": source_event["event_id"],
            "source": source_event["source"],
            "stream": source_event["stream"],
            "record_key": source_event["record_key"],
            "kind": source_event["kind"],
            "observed_at": source_event["observed_at"],
            "content_hash": content_hash,
            "batch_id": source_event["batch_id"],
        }
        if source_event["occurred_at"] is not None:
            envelope["occurred_at"] = source_event["occurred_at"]
        canonical_envelope = jcs(envelope)
        event_hash = sha256(canonical_envelope.encode())
        require(
            canonical_envelope == source_event["canonical_envelope"],
            f"lifecycle {source_event['role']} envelope bytes",
        )
        require(
            event_hash == source_event["event_hash"],
            f"lifecycle {source_event['role']} event_hash",
        )
        events.append(
            {
                **envelope,
                "payload": payload,
                "event_hash": event_hash,
                "role": source_event["role"],
            }
        )

    event_ids = [event["event_id"] for event in events]
    require(event_ids == sorted(event_ids), "lifecycle event order")
    require(len(set(event_ids)) == len(event_ids), "lifecycle event IDs are unique")

    covered_indexes: list[int] = []
    for batch in vector["batches"]:
        indexes = batch["event_indexes"]
        covered_indexes.extend(indexes)
        batch_events = [events[index] for index in indexes]
        require(bool(batch_events), f"lifecycle {batch['role']} is non-empty")
        require(
            all(event["source"] == batch["source"] for event in batch_events),
            f"lifecycle {batch['role']} source",
        )
        require(
            all(event["batch_id"] == batch["batch_id"] for event in batch_events),
            f"lifecycle {batch['role']} batch_id",
        )
        descriptors = []
        for event in batch_events:
            descriptor = {
                "stream": event["stream"],
                "record_key": event["record_key"],
                "kind": event["kind"],
                "content_hash": event["content_hash"],
            }
            if "occurred_at" in event:
                descriptor["occurred_at"] = event["occurred_at"]
            descriptors.append(descriptor)
        require(descriptors == batch["descriptors"], f"lifecycle {batch['role']} descriptors")
        preimage = jcs({"v": 1, "source": batch["source"], "events": descriptors})
        digest = sha256(preimage.encode())
        require(preimage == batch["digest_preimage"], f"lifecycle {batch['role']} preimage")
        require(digest == batch["batch_digest"], f"lifecycle {batch['role']} digest")
        for index in indexes:
            event = events[index]
            tail_line = {
                key: event[key]
                for key in [
                    "event_id",
                    "source",
                    "stream",
                    "record_key",
                    "kind",
                    "observed_at",
                    "content_hash",
                    "batch_id",
                    "event_hash",
                    "payload",
                ]
            }
            if "occurred_at" in event:
                tail_line["occurred_at"] = event["occurred_at"]
            tail_line["batch_len"] = len(indexes)
            tail_line["batch_digest"] = digest
            require(
                jcs(tail_line) == vector["events"][index]["tail_line"],
                f"lifecycle {event['role']} tail bytes",
            )
    require(
        sorted(covered_indexes) == list(range(len(events))),
        "lifecycle batches partition events",
    )

    chain = vector["chain"]
    head = hashlib.sha256(chain["genesis_preimage"].encode("ascii")).digest()
    require(head.hex() == chain["genesis_head"], "lifecycle genesis head")
    heads = []
    for event in events:
        head = hashlib.sha256(head + bytes.fromhex(event["event_hash"])).digest()
        heads.append(head.hex())
    require(heads == chain["heads"], "lifecycle chain heads")

    rules = vector["rules"]
    predecessor = rules["predecessor_source"]
    successor = rules["successor_source"]
    final_frontier = rules["final_frontier"]
    retirement_index = rules["retirement_event_index"]
    lineage_index = rules["successor_lineage_event_index"]
    retirement = events[retirement_index]
    lineage = events[lineage_index]
    predecessor_events = [
        event
        for index, event in enumerate(events)
        if index < retirement_index and event["source"] == predecessor
    ]
    require(bool(predecessor_events), "lifecycle predecessor exists")
    require(predecessor_events[-1]["event_id"] == final_frontier, "retirement frontier")
    require(
        not any(
            index > retirement_index and event["source"] == predecessor
            for index, event in enumerate(events)
        ),
        "no predecessor event after retirement",
    )
    retirement_payload = dict(retirement["payload"])
    require(retirement["source"] == "system", "retirement source")
    require(retirement["stream"] == "groundhog.source_lifecycle", "retirement stream")
    require(retirement["record_key"] == predecessor, "retirement record_key")
    require(retirement["kind"] == "source_retired", "retirement kind")
    require("occurred_at" not in retirement, "retirement occurred_at omitted")
    require(
        retirement_payload
        == {"v": 1.0, "source": predecessor, "final_frontier": final_frontier},
        "retirement payload",
    )
    require(
        retirement["batch_id"] == f"groundhog/retire/{predecessor}/{final_frontier}",
        "retirement batch_id",
    )

    lineage_payload = dict(lineage["payload"])
    require(successor != predecessor, "successor differs from predecessor")
    require(lineage["source"] == successor, "lineage successor source")
    require(lineage["stream"] == "groundhog.source_lineage", "lineage stream")
    require(lineage["record_key"] == predecessor, "lineage record_key")
    require(lineage["kind"] == "source_succeeded", "lineage kind")
    require("occurred_at" not in lineage, "lineage occurred_at omitted")
    require(
        lineage_payload
        == {
            "v": 1.0,
            "predecessor_source": predecessor,
            "predecessor_final_frontier": final_frontier,
        },
        "lineage payload",
    )
    require(
        not any(event["source"] == successor for event in events[:lineage_index]),
        "lineage is the successor first event",
    )
    lineage_batch = next(
        batch for batch in vector["batches"] if lineage_index in batch["event_indexes"]
    )
    position = lineage_batch["event_indexes"].index(lineage_index)
    require(position == rules["successor_lineage_batch_position"], "lineage batch position")


def verify_stream_precondition() -> None:
    vector = load_json("stream_precondition.json")
    submitted_events = []
    descriptors = []
    for source_event in vector["events"]:
        payload = parse_payload(source_event["payload_input"])
        payload_canonical = jcs(payload)
        content_hash = sha256(payload_canonical.encode())
        require(payload_canonical == source_event["payload_canonical"], "precondition payload")
        require(content_hash == source_event["content_hash"], "precondition content_hash")
        submitted = {
            "stream": source_event["stream"],
            "record_key": source_event["record_key"],
            "kind": source_event["kind"],
            "payload": payload,
        }
        descriptor = {
            "stream": source_event["stream"],
            "record_key": source_event["record_key"],
            "kind": source_event["kind"],
            "content_hash": content_hash,
        }
        if source_event["occurred_at"] is not None:
            submitted["occurred_at"] = source_event["occurred_at"]
            descriptor["occurred_at"] = source_event["occurred_at"]
        submitted_events.append(submitted)
        descriptors.append(descriptor)
    require(descriptors == vector["descriptors"], "precondition descriptors")
    preimage = jcs({"v": 1, "source": vector["source"], "events": descriptors})
    digest = sha256(preimage.encode())
    require(preimage == vector["digest_preimage"], "precondition digest preimage")
    require(digest == vector["batch_digest"], "precondition batch_digest")
    require("stream_precondition" not in preimage, "precondition excluded from digest")

    variants = {variant["name"]: variant for variant in vector["request_variants"]}
    canonical_requests = set()
    for variant in variants.values():
        request = {
            "v": 1,
            "batch_id": vector["batch_id"],
            "source": vector["source"],
            "events": submitted_events,
        }
        condition = variant["stream_precondition"]
        if condition is not None:
            request["stream_precondition"] = condition
            require(
                all(event["stream"] == condition["stream"] for event in submitted_events),
                f"precondition {variant['name']} stream scope",
            )
        canonical_request = jcs(request)
        canonical_requests.add(canonical_request)
        require(
            canonical_request == variant["canonical_request"],
            f"precondition {variant['name']} request bytes",
        )
        require(
            jcs(parse_json(canonical_request)) == canonical_request,
            f"precondition {variant['name']} request closure",
        )
        require(variant["batch_digest"] == digest, f"precondition {variant['name']} digest")
    require(len(canonical_requests) == len(variants), "precondition request variants differ")
    require(
        len({variant["batch_digest"] for variant in variants.values()}) == 1,
        "precondition variants share one digest",
    )

    for scenario in vector["admission_scenarios"]:
        variant = variants[scenario["variant"]]
        existing = scenario["existing_batch_digest"]
        condition = variant["stream_precondition"]
        if existing is not None:
            outcome = "duplicate" if existing == digest else "batch_id_conflict"
            reserves_batch_id = False
        elif condition is not None and scenario["actual_frontier"] != condition["expected_frontier"]:
            outcome = "stream_frontier_conflict"
            reserves_batch_id = False
        else:
            outcome = "committed"
            reserves_batch_id = True
        require(outcome == scenario["outcome"], f"precondition {scenario['name']} outcome")
        require(
            reserves_batch_id == scenario["reserves_batch_id"],
            f"precondition {scenario['name']} reservation",
        )


def main() -> None:
    verify_jcs()
    verify_content_hashes()
    events = recompute_events()
    digest = verify_batch(events)
    head = verify_chain(events)
    verify_storage_records(events, digest, head)
    verify_lifecycle()
    verify_stream_precondition()
    print(f"Compatibility vectors verified independently with {sys.implementation.name} {sys.version.split()[0]}")


if __name__ == "__main__":
    try:
        main()
    except (VectorFailure, AssertionError, KeyError, TypeError, ValueError) as error:
        print(f"vector verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

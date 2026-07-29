# Batch Append Contract

This document defines `POST /v1/events` for contract version 1.

## Request

The client MUST send `Content-Type: application/json`. The encoded request body MUST NOT exceed 32
MiB.

The request MUST match [`schemas/append-batch.schema.json`](schemas/append-batch.schema.json). The
batch object is closed. Each submitted event is also closed.

The `v` member is optional. An omitted `v` means version 1. A present `v` MUST equal 1.

The `events` array MUST contain between 1 and 10,000 events. Array order is submission order and
becomes commit order.

Groundhog MUST validate the complete batch before it commits any event. A validation error rejects
the complete batch.

Groundhog SHOULD report every invalid event with its zero-based array index. It MUST NOT accept the
valid subset of an invalid batch.

## Batch identity

The idempotency key is the pair `(source, batch_id)`. A `batch_id` has no identity outside its
source.

Groundhog binds the key to one `batch_digest`. The digest is lowercase hexadecimal SHA-256 over
this RFC 8785 canonical object:

```json
{
  "v": 1,
  "source": "example",
  "events": [{
    "stream": "contacts",
    "record_key": "contact-42",
    "kind": "upserted",
    "occurred_at": "2026-07-07T08:58:41.5Z",
    "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  }]
}
```

Each digest event contains `stream`, `record_key`, `kind`, and `content_hash`. It contains
`occurred_at` only when the submitted event contains that member.

The digest preserves event order. It does not contain `batch_id` or `stream_precondition`.

Groundhog MUST resolve an existing `(source, batch_id)` before retirement and precondition checks.
The comparison uses the new request's computed digest.

If the digest matches, Groundhog MUST return the original receipt with status `duplicate`. It MUST
NOT append a second copy.

If the digest differs, Groundhog MUST return `409 batch_id_conflict`. It MUST NOT change the log.

## Stream precondition

`stream_precondition` is optional admission metadata. It contains exactly `stream` and
`expected_frontier`.

Every event in the batch MUST use the precondition's stream. The source comes from the batch
envelope.

A UUIDv7 `expected_frontier` requires an exact match with the latest committed event in that
source and stream. A null value requires that the stream has no committed event.

Groundhog MUST evaluate the precondition and append as one serialized writer operation. A mismatch
returns `409 stream_frontier_conflict` and commits nothing.

A mismatch MUST NOT reserve `(source, batch_id)`. The client can retry that key with different
content after it gets new state.

Groundhog MUST NOT store the precondition in committed events. The precondition does not affect
the batch digest, replay, projection, rebuild, or verification.

## Admission order

Groundhog MUST use this order for a valid request:

1. Resolve an existing `(source, batch_id)`.
2. Refuse a new batch for a retired source.
3. Validate an optional successor-lineage marker.
4. Evaluate the optional stream precondition.
5. Commit the complete batch.

Concurrent mutations have one writer order. A client can observe any order that satisfies these
rules.

## Commit and receipt

Groundhog MUST assign consecutive log positions to the complete batch. No reader can observe a
partial batch.

A `committed` receipt means the complete batch reached the durable committed log. A client
disconnect does not cancel work that has entered the writer.

An uncertain client SHOULD retry the same `(source, batch_id)` and content. The retry returns the
original receipt after the first request committed.

A success response uses HTTP 200 and matches
[`schemas/append-receipt.schema.json`](schemas/append-receipt.schema.json).

`events` is the original event count. `first_event_id` and `last_event_id` identify the inclusive
committed range.

`batch_digest` and all receipt fields MUST stay identical for every successful retry. Only `status`
changes from `committed` to `duplicate`.

Invalid input returns HTTP 400. An oversized body or event array returns HTTP 413. An unavailable
admission slot returns HTTP 429 without reading or committing the batch.

Conflicts return HTTP 409. A poisoned writer returns HTTP 503. Error bodies follow
[`errors.md`](errors.md).

# Source Lifecycle Contract

This document defines source retirement and successor lineage for contract version 1.

## Retirement request

`POST /v1/sources/retire` permanently closes one source to new append batches. The client MUST send
`Content-Type: application/json` and no query parameters.

The encoded body MUST NOT exceed 1 MiB. The body MUST match
[`schemas/retirement-request.schema.json`](schemas/retirement-request.schema.json).

The request is a closed object. The optional `v` defaults to 1 and MUST equal 1 when present.

The source MUST have at least one committed event. The source `system` cannot be retired.

An unknown source returns HTTP 404 with code `source_not_found`. Invalid input returns HTTP 400.

## Retirement operation

The writer MUST read the source frontier and append the retirement event as one serialized
operation. Another mutation cannot occur between those actions.

The retirement event MUST have these values:

| Field | Value |
| --- | --- |
| `source` | `system` |
| `stream` | `groundhog.source_lifecycle` |
| `record_key` | the retired source |
| `kind` | `source_retired` |
| `occurred_at` | omitted |
| `payload` | the retirement payload |
| `batch_id` | `groundhog/retire/{source}/{final_frontier}` |

The retirement payload MUST match
[`schemas/retirement-payload.schema.json`](schemas/retirement-payload.schema.json). Its
`final_frontier` is the latest committed event for the retired source.

The retirement event is an ordinary committed event. Replay and local projection include it. Its
hashes, batch commitment, and integrity-chain position follow the normal rules.

The retirement response uses HTTP 200. It MUST match
[`schemas/retirement-response.schema.json`](schemas/retirement-response.schema.json).

The first successful request returns status `retired`. A later request for the same source returns
status `already_retired` and the same fields.

Retirement is permanent. It does not rename, delete, seal, compact, or otherwise change the
retired history.

## Append after retirement

A new batch for a retired source returns HTTP 409 with code `source_retired`. The response identifies
the final source frontier and the retirement event.

Groundhog resolves a committed `(source, batch_id)` before this refusal. An identical accepted
retry still returns its original duplicate receipt.

Conflicting reuse of an accepted key still returns `batch_id_conflict`. Groundhog checks retirement
before a stream precondition or lineage marker on a new batch.

A concurrent append and retirement have one writer order. If append commits first, its last event
becomes the final frontier.

If retirement commits first, Groundhog refuses the new append. A response MUST match one of these
two orders.

## Successor lineage

A source can declare one retired predecessor. The declaration uses a reserved submitted event in
the successor source's first batch.

The lineage event MUST be the first event in that batch. It MUST also be the first committed event
for the successor source.

The batch MUST contain exactly one event with stream `groundhog.source_lineage`. That event MUST
have these submitted values:

| Field | Value |
| --- | --- |
| `stream` | `groundhog.source_lineage` |
| `record_key` | the predecessor source |
| `kind` | `source_succeeded` |
| `occurred_at` | omitted |
| `payload` | the lineage payload |

The payload MUST match
[`schemas/lineage-payload.schema.json`](schemas/lineage-payload.schema.json). `record_key` MUST equal
`predecessor_source`.

The successor MUST differ from its predecessor. The predecessor MUST have a durable retirement at
the exact `predecessor_final_frontier`.

A malformed, repeated, or out-of-order marker returns HTTP 400 with code `invalid_source_lineage`.
A missing or mismatched retirement returns HTTP 409 with code `source_lineage_conflict`.

A source that already has an event cannot add lineage. Groundhog returns
`source_lineage_conflict` and does not commit the batch.

Groundhog commits a valid lineage event atomically with the rest of its batch. Verification MUST
check lineage against retirement records in committed log order.

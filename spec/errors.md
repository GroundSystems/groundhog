# HTTP Error Contract

This document defines machine-readable errors for contract version 1.

## Error object

Every JSON error response MUST match [`schemas/error.schema.json`](schemas/error.schema.json). It has
this base form:

```json
{
  "error": "stream_frontier_conflict",
  "message": "The current stream frontier does not match the request.",
  "source": "example",
  "stream": "contacts",
  "expected_frontier": null,
  "actual_frontier": "019c0000-0000-7000-8000-000000000001"
}
```

`error` is the stable machine code. `message` is a non-empty description for people.

Clients MUST use `error` for control flow. They MUST NOT compare `message` text.

Message wording, punctuation, capitalization, and detail can change without a contract version
change. An implementation MAY localize a message.

Endpoint-specific members provide structured context. A client MUST retain or ignore unknown
members instead of rejecting the response.

A client MUST handle an unknown machine code as an error with the received HTTP status. Adding a
new code is an additive contract change.

Changing a code's meaning, HTTP status, or required structured members requires a new contract
version.

## Shared codes

| Code | HTTP status | Meaning |
| --- | ---: | --- |
| `invalid_request` | 400 | The request syntax or closed envelope is invalid. |
| `invalid_batch` | 400 | Batch-level validation failed. |
| `invalid_events` | 400 | One or more submitted events are invalid. |
| `invalid_source_retirement` | 400 | The retirement request is invalid. |
| `invalid_source_lineage` | 400 | A lineage marker is malformed or out of order. |
| `invalid_replay_request` | 400 | A replay parameter is invalid. |
| `invalid_streams_request` | 400 | A stream enumeration parameter is invalid. |
| `stream_anchor_unavailable` | 400 | The requested stream anchor is not committed and available. |
| `unauthorized` | 401 | Authentication is required or invalid. |
| `not_found` | 404 | The requested route does not exist. |
| `source_not_found` | 404 | The source has no committed event and cannot be retired. |
| `method_not_allowed` | 405 | The route does not accept the HTTP method. |
| `batch_id_conflict` | 409 | The idempotency key has different committed content. |
| `source_retired` | 409 | The source permanently refuses a new batch. |
| `source_lineage_conflict` | 409 | The predecessor or successor state conflicts with lineage. |
| `stream_frontier_conflict` | 409 | The current stream frontier differs from the precondition. |
| `body_too_large` | 413 | The request exceeds a byte or item limit. |
| `unsupported_media_type` | 415 | The request does not use the required media type. |
| `overloaded` | 429 | Bounded admission expired before work started. |
| `internal_error` | 500 | An unexpected server failure occurred. |
| `writer_poisoned` | 503 | A mutation outcome is uncertain and the writer session is closed. |

Authentication is outside the shared operation contract. A deployment that requires
authentication SHOULD use `unauthorized` without exposing route state first.

`overloaded` MUST mean that the rejected operation did not enter its mutation. The response SHOULD
include a valid `Retry-After` header.

`writer_poisoned` MUST NOT claim that the uncertain mutation failed. The client MUST reopen or use
a new serving session before it retries.

## Stable conflict context

`batch_id_conflict` includes `source` and `batch_id`.

`source_retired` includes `source`, `final_frontier`, and `retirement_event_id`.

`stream_frontier_conflict` includes `source`, `stream`, `expected_frontier`, and `actual_frontier`.
Either frontier can be null.

`source_lineage_conflict` includes `source`, `predecessor_source`,
`expected_predecessor_frontier`, and `actual_predecessor_frontier`. The actual frontier can be null.

`source_not_found` includes `source`.

These member names and value meanings are stable. A response MAY add other descriptive members.

## Indexed event errors

`invalid_events` includes an `errors` array. Each item contains a zero-based `index`, stable `code`,
and non-stable `message`.

The item code `invalid_event` means that the submitted event at that index failed validation.
Groundhog MAY add more specific item codes later.

The response SHOULD include every invalid event that Groundhog can identify without mutation. The
complete batch still fails atomically.

## Local query codes

These codes apply only to the local query and catalog contract:

| Code | HTTP status | Meaning |
| --- | ---: | --- |
| `invalid_query_request` | 400 | The query envelope is invalid. |
| `query_rejected` | 400 | SQL confinement, binding, execution, or rendering rejected the query. |
| `invalid_catalog_request` | 400 | A catalog parameter is invalid. |
| `query_timeout` | 408 | The engine confirmed timeout cancellation. |
| `catalog_unavailable` | 500 | The published catalog generation cannot be read. |

Engine diagnostic text belongs in `message`. Its exact text is not stable.

## SDK behavior

An SDK error type SHOULD expose the HTTP status, machine code, message, and structured members. It
SHOULD preserve the response body for diagnostics.

An SDK MUST NOT map an unknown code to success. It SHOULD provide a generic remote-error type that
retains the unknown code.

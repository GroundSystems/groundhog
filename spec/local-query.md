# Local Query and Projection Contract

This document defines local runtime behavior. It is outside the shared Groundhog Cloud contract.

## Projection boundary

The append-only event log is durable state. The DuckDB warehouse is derived and replaceable state.

Append, replay, and stream enumeration do not update or read the warehouse. The `project` and
`rebuild` commands explicitly publish a warehouse generation.

Each publication captures one coherent committed log frontier. It publishes the `events` relation,
stream metadata, and one receipt in one replacement operation.

An append after that capture does not appear until a later publication. Query and catalog results
can therefore lag durable replay and stream enumeration.

Each query or catalog request pins one complete published generation. A concurrent publication can
become visible between requests but cannot change a request in progress.

The same committed frontier, projection version, and compatible build MUST produce the same
logical relations and receipt. Groundhog does not require byte-identical DuckDB files.

Projection code MUST NOT use the wall clock, randomness, or external I/O to derive logical state.

## Projection receipt

Every successful query and catalog response contains this receipt:

| Member | Meaning |
| --- | --- |
| `as_of_event_id` | inclusive projected event frontier, or null for an empty log |
| `chain_head` | lowercase chain head at the projected frontier |
| `groundhog_version` | build version that made the projection |
| `storage_schema_version` | interpreted durable storage schema |
| `projections_hash` | lowercase hash of the projection definition set |

The version 1 runtime has no deployment projection definitions. Its `projections_hash` is the
SHA-256 hash of empty bytes:

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Clients MUST compare `as_of_event_id` with durable frontiers before they make freshness claims.

## Query request

`POST /v1/query` runs one read-only SQL statement against the pinned warehouse. The client MUST
send `Content-Type: application/json`.

The encoded body MUST NOT exceed 1 MiB. The request is a closed object with these members:

| Member | Type | Requirement |
| --- | --- | --- |
| `sql` | string | required |
| `format` | string | optional and only `json` |
| `limit` | positive integer | optional row limit |
| `timeout_secs` | positive integer | optional timeout |

The local defaults are 10,000 rows and 30 seconds. The default maximum is 1,000,000 rows. The
configured timeout is also the maximum timeout.

Groundhog rejects an out-of-range value instead of reducing it. A timeout response uses HTTP 408
only after the engine confirms cancellation.

Client SQL can read `events`, `meta.streams`, and `meta.projection_state`. Groundhog MUST reject a
mutation, multiple statements, external access, volatile behavior, or an unpublished relation.

A query with an explicit limit or a truncated result requires a total top-level `ORDER BY` over
the result columns. Groundhog rejects the complete result when this condition is false.

## Query response

A successful query uses HTTP 200 and returns this closed JSON object:

```json
{
  "columns": ["source", "events"],
  "receipt": {
    "as_of_event_id": "019c0000-0000-7000-8000-000000000001",
    "chain_head": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "groundhog_version": "1.0.0",
    "storage_schema_version": 1,
    "projections_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  "rows": [["example", 2]],
  "truncated": false
}
```

Each row is an array aligned with `columns`. `truncated` is always present.

Null renders as JSON null. Integers in the safe binary64 range render as numbers. Wider integers
render as exact decimal strings.

Decimal values render as exact strings at their declared scale. Finite floats render as JSON
numbers, and a non-finite float rejects the complete query.

UUID values render as lowercase strings. JSON values render as embedded JSON after I-JSON
validation. Temporal, interval, enum, and blob values render as documented strings.

Lists and arrays render as arrays. Structs render as objects. Maps render as ordered `key` and
`value` pairs.

The retained result and encoded response each have a 64 MiB ceiling. Groundhog rejects an oversized
complete result without sending a partial success body.

## Catalog

`GET /v1/catalog` accepts optional exact `source` and `stream` query parameters. Unknown or repeated
parameters return HTTP 400.

The response contains `receipt` and `streams`. `receipt` is the pinned generation receipt.

Each stream row contains `source`, `stream`, `event_count`, `first_observed_at`,
`last_observed_at`, and sorted distinct `kinds`.

Catalog counts and timestamps describe only the published frontier. They can differ from direct
stream enumeration until the next publication.

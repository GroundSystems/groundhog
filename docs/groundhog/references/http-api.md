---
title: Groundhog HTTP API
description: Groundhog 0.3 transport, authentication, log routes, errors, and retry behavior.
---

## Name

`groundhog-http`: the version 1 log and indexed Query API over a Unix domain socket.

Groundhog stores and serves the durable event log.
Applications can build derived views from replay or follow. A local deployment can also enable
typed indexed reads over immutable Query snapshots.

## Transport

The service speaks HTTP/1.1 over the Unix socket configured by `[server].socket`.
It does not listen on TCP.

HTTP/1.1 requires a `Host` header, but Groundhog ignores its value.

```sh
curl --unix-socket data/ground.sock http://ground/v1/streams
```

Request and response bodies use UTF-8 JSON unless a follow response uses NDJSON.

The three `POST` routes accept `Content-Type: application/json` or no content type.
Groundhog accepts `charset=utf-8` as the only optional parameter.
Other parameters or media types return 415 before Groundhog reads the body.
Any `Content-Encoding` header also returns 415 before body reading.

## Authentication

If `[server].token` is not empty, every request needs:

```text
Authorization: Bearer <token>
```

Use this command to supply the header with `curl`:

```sh
curl --unix-socket data/ground.sock \
  -H 'Authorization: Bearer <token>' \
  http://ground/v1/streams
```

A missing or incorrect token returns:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"error":"unauthorized","message":"The request does not have valid authorization."}
```

Authorization occurs before routing, admission, or body reading.
Groundhog ignores the authorization header when the configured token is empty.

## Current routes

| method | path | purpose |
|---|---|---|
| `POST` | `/v1/events` | Append an atomic JSON event batch. |
| `GET`, `HEAD` | `/v1/events` | Replay events or follow new commits. |
| `GET`, `HEAD` | `/v1/streams` | Enumerate authoritative streams. |
| `POST` | `/v1/sources/retire` | Permanently retire one source. |
| `POST` | `/v1/query` | Run one structured query or one named multi-query request. |
| `GET`, `HEAD` | `/v1/catalog` | List relation schemas and snapshot metadata. |
| `GET`, `HEAD` | `/v1/catalog/relations/{relation}` | Read one relation declaration. |
| `GET`, `HEAD` | `/v1/projections/{projection}/status` | Read one projection's snapshot and freshness. |

An unknown path returns 404.
A known path with another method returns 405 and an `Allow` header.
`HEAD` returns the same status and headers as `GET` without a body.

The Query, Catalog, and projection-status routes exist only when `[query].enabled = true`.
The enabled service requires a non-empty bearer token.
A disabled deployment does not register these routes.

## Error documents

Errors use a stable code and a separate message:

```json
{
  "error": "invalid_replay_request",
  "message": "The request contains an invalid replay parameter."
}
```

Clients must use the HTTP status and known `error` codes for control flow.
They must not match `message` text because that text can change.
Clients must retain or ignore unknown top-level fields.
An unknown `error` code remains an error with the received HTTP status.

Some conflicts add typed top-level fields.
Per-event validation adds an `errors` array with zero-based indexes, stable codes, and messages.

Groundhog rejects repeated query parameters, duplicate JSON member names, and unknown body members.
Control envelopes have a 1 MiB limit.
JSON ingest has a separate 32 MiB limit.

## `POST /v1/events`

Append one atomic batch:

```json
{
  "v": 1,
  "batch_id": "stripe-sync-2026-07-14-001",
  "source": "stripe",
  "events": [
    {
      "stream": "customers",
      "record_key": "cus_9XKzR2",
      "kind": "upserted",
      "occurred_at": "2026-07-14T16:30:00Z",
      "payload": {"id": "cus_9XKzR2", "email": "kim@example.com"}
    }
  ]
}
```

`v` defaults to 1.
`source` and `batch_id` belong to the batch.
This route does not accept query parameters.

Each submitted event has `stream`, `record_key`, `kind`, optional `occurred_at`, and `payload`.
Groundhog rejects the complete batch when any event is invalid.

A batch contains 1 through 10,000 events and no more than 32 MiB of request-body JSON.
Source, stream, and kind values use at most 128 UTF-8 bytes.
Record keys use at most 1,024 UTF-8 bytes, and batch IDs use at most 256 UTF-8 bytes.
Source and stream names match `[a-z0-9_][a-z0-9_.-]*`.
Groundhog reserves the `system` source and the `groundhog/` batch ID prefix.

Groundhog canonicalizes accepted payloads with RFC 8785 rules.
It rejects non-finite numbers and precision-losing integer aliases.
It also rejects payloads deeper than 128 containers.
An `occurred_at` value must be a valid UTC calendar time with a final `Z`.
It can omit fractional seconds or use one through nine fractional digits.
Numeric offsets and leap seconds are invalid.

### Idempotency

`(source, batch_id)` identifies one batch for the life of the data directory.
Groundhog computes a canonical digest before it assigns server fields.
The digest binds the source and ordered submitted event content.
It excludes `batch_id`, `stream_precondition`, and server-assigned fields.

A new batch returns:

```json
{
  "status": "committed",
  "batch_digest": "<64 lowercase hex characters>",
  "events": 1,
  "first_event_id": "<UUIDv7>",
  "last_event_id": "<UUIDv7>"
}
```

A retry with the same key and digest returns the original receipt with `status: "duplicate"`.
The retry writes nothing after lifecycle state or the stream frontier changes.
Different digested content with the same key returns `409 batch_id_conflict` and writes nothing.

A successful receipt means the complete batch is durable.
Retry the same submitted events with the same key after a lost response.

### Optional stream precondition

`stream_precondition` requires one stream to have an expected frontier before the batch commits.
Every event in the batch must target that stream.

```json
{
  "stream_precondition": {
    "stream": "customers",
    "expected_frontier": "019c0000-0000-7000-8000-000000000001"
  }
}
```

Set `expected_frontier` to `null` to require a stream with no committed events.
A mismatch returns `409 stream_frontier_conflict` and commits nothing.

## `GET /v1/events`

Finite replay returns authoritative history in increasing `event_id` order:

```text
GET /v1/events?after=<event_id>&source=stripe&stream=customers&record_key=cus_9XKzR2&kind=upserted&limit=1000
```

All parameters are optional and use exact matches.
`after` is exclusive.

`limit` must be positive and cannot exceed `[replay].max_limit`.
Omission uses `[replay].default_limit`.

A finite response has this shape:

```json
{
  "events": [
    {
      "event_id": "...",
      "source": "stripe",
      "stream": "customers",
      "record_key": "cus_9XKzR2",
      "kind": "upserted",
      "occurred_at": "2026-07-14T16:30:00Z",
      "observed_at": "...",
      "payload": {"id": "cus_9XKzR2"},
      "content_hash": "...",
      "batch_id": "stripe-sync-2026-07-14-001",
      "event_hash": "..."
    }
  ],
  "last_event_id": "...",
  "next_after": "...",
  "snapshot_through_event_id": "...",
  "snapshot": {
    "frontier_event_id": "...",
    "frontier_event_count": 42,
    "chain_head": "<64 lowercase hex characters>"
  }
}
```

`last_event_id` is the last matching event and is absent for an empty result.
It is not the progress cursor for a filtered consumer.

`next_after` is the last position that the request conclusively scanned.
Persist it for the next finite poll.
A finite page can contain fewer events than `limit` when it reaches the response-size bound.

`snapshot_through_event_id` is the coherent frontier captured for the request.
It is `null` only for an empty log.

`snapshot` is the complete event snapshot receipt. It is additive to the older replay cursor fields.

### Follow mode

Add `follow=true` to receive the initial snapshot and later commits on one response.

```sh
curl --no-buffer --unix-socket data/ground.sock \
  'http://ground/v1/events?follow=true&source=stripe&stream=customers'
```

Follow uses `Content-Type: application/x-ndjson` and returns one JSON record per line.
The response includes `Connection: close`.

The records have three forms:

- `events` records contain replay fields and a `phase` of `snapshot` or `live`.
- A `caught_up` record marks the end of the initial snapshot and includes its complete `snapshot`
  receipt.
- An `end` record gives a terminal reason and the last delivered event ID.

Terminal reasons are `shutdown`, `writer_poisoned`, `session_closed`, `buffer_exceeded`, and `replay_failed`.
An `end` record can include a descriptive `detail` field.
EOF without an `end` record is a transport failure.

In follow mode, `limit` bounds each `events` record.
It does not end the response.

Persist each delivered event's `event_id`.
Reconnect with `after=<last delivered event_id>` and the same filters.

`follow=false` or an omitted `follow` returns one finite JSON response.

## `GET /v1/streams`

This route scans the durable log and returns source and stream summaries.
It does not use derived state.

```text
GET /v1/streams?source=stripe&limit=100
```

The optional parameters are `source`, `after`, `through`, and `limit`.
Results use source order followed by stream order.
The `after` value is an exclusive `source/stream` cursor.

```json
{
  "v": 1,
  "streams": [
    {
      "source": "stripe",
      "stream": "customers",
      "frontier_event_id": "019c0000-0000-7000-8000-000000000001",
      "event_count": 42
    }
  ],
  "next_after": null,
  "snapshot_through_event_id": "019c0000-0000-7000-8000-000000000001"
}
```

Pages contain 100 rows by default and at most 1,000 rows.

When `next_after` is not null, send it as `after` on the next request.
Also send the first response's `snapshot_through_event_id` as `through`.
Groundhog rejects `after` without `through`.

The anchor excludes later commits, so all pages describe one logical stream snapshot.

## `POST /v1/sources/retire`

Permanently close one source to new batches:

```json
{
  "v": 1,
  "source": "stripe"
}
```

This route does not accept query parameters.
`v` defaults to 1.
The source must have at least one committed event.
Operators cannot retire the reserved `system` source.

A first success returns:

```json
{
  "v": 1,
  "status": "retired",
  "source": "stripe",
  "final_frontier": "019c0000-0000-7000-8000-000000000001",
  "retirement_event_id": "019c0000-0001-7000-8000-000000000002"
}
```

A repeat returns the same fields with `status: "already_retired"`.
A new batch for the retired source returns `409 source_retired`.

Retirement does not rename, delete, seal, or compact existing history.
It appends one event under source `system` and stream `groundhog.source_lifecycle`.
The event uses kind `source_retired` and the retired source as its record key.

A successor can declare one retired predecessor in its first batch.
The first submitted event uses stream `groundhog.source_lineage` and kind `source_succeeded`.
Its record key equals the predecessor source, and it omits `occurred_at`.
Its closed payload contains `v`, `predecessor_source`, and `predecessor_final_frontier`.
The declared frontier must equal the predecessor's durable retired frontier.

Groundhog returns `400 invalid_source_lineage` for a malformed or misplaced marker. It returns
`409 source_lineage_conflict` when the predecessor retirement or successor state conflicts.

## `POST /v1/query`

Query accepts one closed version 1 JSON envelope of at most 1 MiB. It rejects query parameters,
duplicate JSON members, unknown object members, invalid UTF-8, unsupported media types, and any
`Content-Encoding` before execution.

The current binary enables Query only for the local event-log backend. It exposes
`groundhog.events` and the complete Agent Operations version 1 relation pack.
This request is also the validated
[`event-row-query.json`](https://github.com/GroundSystems/groundhog/blob/main/verify/conformance/fixtures/query-v1/valid/event-row-query.json)
fixture:

```json
{
  "v": 1,
  "consistency": {"mode": "published"},
  "query": {
    "relation": "groundhog.events",
    "select": ["event_id", "source", "stream", "kind", "observed_at"],
    "filter": {"op": "eq", "field": "source", "value": "stripe"},
    "order_by": [{"field": "event_id", "direction": "asc"}],
    "limit": 100
  }
}
```

The envelope contains exactly one of:

- `query`, which produces one result named `query`
- `queries`, which contains 1 through 16 distinct named query objects.

Groundhog pins one immutable snapshot for the complete request. Every named query succeeds, or the
request returns one error with no partial result.

### Query structure

A row query contains `relation` and `select`. It can also contain `filter`, `order_by`, `limit`, and
`after`. An omitted `limit` uses `query.default_page_rows`, which defaults to 100. A supplied value
cannot exceed `query.max_page_rows`.

The filter operators are:

- Boolean: `and`, `or`, and `not`.
- Comparison: `eq`, `not_eq`, `lt`, `lte`, `gt`, and `gte`.
- Set: `in` and `not_in`.
- List: `contains` and `contains_any`.
- Null: `is_null` and `is_not_null`.

Values must use the declared field type. `i64` and `u64` values use canonical decimal strings.
Finite `f64` values use JSON numbers. UUID and timestamp values use canonical strings. A timestamp
filter uses UTC with exactly six fractional digits. JSON fields cannot be filtered.

The planner requires a declared index for bounded access or ordering. It returns
`409 index_required` when a request needs another access path.

The version 1 schema defines grouped `count` and numeric `sum` requests. The projected-relation
executor implements those operations for the Agent Operations relations. Aggregate ordering
can reference group fields or measure names. Grouped aggregates do not accept `after`. The
`groundhog.events` planner accepts `count` with or without `group_by`. It has no numeric field, so
a `sum` measure over `groundhog.events` returns `400 invalid_query`. It reads the input in
event-identifier order and orders the completed groups, so aggregate ordering does not need an
event index.

A `groundhog.events` aggregate must read its whole matching input inside the scan-row budget that
remains for the request. A larger input returns `422 query_limit_exceeded`. The route never returns
a partial aggregate. Both relation kinds also return `422 query_limit_exceeded` when the completed
groups reach `max_aggregate_groups`.

Signed cursors bind the query, schema, order, authorization scope, expiry, and original immutable
snapshot. See
[Query and Catalog](/groundhog/concepts/query) for the current indexed fields and order rules.

### Consistency

`{"mode":"published"}` reads the current valid Query snapshot.

`at_least` supplies a complete event receipt and a positive wait timeout:

```json
{
  "mode": "at_least",
  "receipt": {
    "frontier_event_id": "019c0000-0000-7000-8000-000000000004",
    "frontier_event_count": 4,
    "chain_head": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  },
  "wait_timeout_ms": 5000
}
```

Groundhog validates the receipt against event history. A mismatch returns
`409 frontier_chain_mismatch`. A valid frontier that is not published before the timeout returns
`504 projection_frontier_timeout`. The serving-session publication worker can publish a later valid
frontier while the request waits. The requested wait cannot exceed `query.max_timeout_ms`.

### Query response

A success contains one query snapshot receipt and one result per requested query:

```json
{
  "v": 1,
  "query_id": "qry_019c0000000070008000000000000001",
  "snapshot": {
    "snapshot_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "frontier_event_id": "019c0000-0000-7000-8000-000000000004",
    "frontier_event_count": 4,
    "chain_head": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "projection_versions": {"groundhog_events": 1},
    "schema_versions": {"groundhog.events": 1}
  },
  "results": [
    {
      "name": "query",
      "columns": [
        {"name": "event_id", "type": "uuid", "nullable": false},
        {"name": "source", "type": "utf8", "nullable": false}
      ],
      "rows": [["019c0000-0000-7000-8000-000000000004", "stripe"]],
      "has_more": false,
      "next_cursor": null,
      "stats": {"rows_examined": 1, "bytes_read": 0, "elapsed_ms": 1}
    }
  ]
}
```

The snapshot receipt identifies the immutable query input. Result rows use column order. The
configured response limit cannot exceed 64 MiB.

## Catalog routes

`GET /v1/catalog` lists every relation visible in the current Query snapshot.
`GET /v1/catalog/relations/{relation}` reads one canonical relation
name. The corresponding `HEAD` operations return the selected GET status and headers without a
body.

Catalog returns:

- relation and projection versions
- field names, types, and nullability
- the primary key
- declared posting and ordered indexes with their supported operations
- row counts and freshness metadata
- the complete Query snapshot receipt.

Catalog reads metadata only. It does not read relation rows. Query parameters return 400. A missing
or invalid relation path returns `404 relation_not_found`.

## Projection status route

`GET /v1/projections/{projection}/status` reads one canonical projection name.
The corresponding `HEAD` operation returns the selected GET status and headers without a body.

Groundhog 0.3 publishes two projections: `agent_operations` from the Agent Operations version 1
pack, and `groundhog_events` behind the built-in `groundhog.events` relation.

A successful response contains:

- the projection name and version
- the immutable Query snapshot receipt
- freshness, which reports the status, the log frontier event count the lag is measured against,
  the event lag, and a failure message when the projection has failed
- cursor retention, which reports the retained snapshot count and the unique retained bytes
- compaction, which reports the delta-compaction phase, the completed and failed run counts, the
  last completed run, and the last failure.

Freshness status is `current`, `catching_up`, or `failed`. The `groundhog_events` projection never
reports `failed`.

Cursor retention and compaction describe the whole Query service, not the requested projection.
Both carry the same values for every projection name.

`404 not_found` covers a name that is not a canonical projection name and a name that no relation
projects.

A service that has not published its first Query snapshot yet returns `503 query_unavailable`, the
same answer the Catalog routes give in that state. A monitoring client that starts with `serve`
reads `503 query_unavailable` until the first snapshot is published.

Query parameters return 400.

## Common status codes

| status | meaning |
|---:|---|
| 200 | Success, including a duplicate ingest receipt. |
| 400 | Invalid request, batch, event, replay, stream, lifecycle, query, or cursor input. |
| 401 | Missing or incorrect bearer token. |
| 404 | Unknown route, source, relation, or field. |
| 405 | Unsupported method on a known route. |
| 408 | Query execution exceeded its timeout. |
| 409 | Batch identity, stream frontier, retirement, lineage, index, or receipt conflict. |
| 410 | A Query cursor or its snapshot expired. |
| 413 | A body or event count exceeded its limit. |
| 415 | Unsupported content type, parameter, or content encoding. |
| 422 | Query exceeded a work or result limit. |
| 429 | Groundhog did not admit the request, execution, consistency wait, or cursor snapshot. Route admission includes `Retry-After`. |
| 500 | Groundhog encountered an unexpected internal failure. |
| 503 | The writer is poisoned, or no valid Query snapshot is available. |
| 504 | Query did not publish a requested valid event frontier before its wait expired. |

A 429 rejected before mutation queue admission writes nothing and is retryable.
Queued mutations reach their real storage result after a client disconnects.

A 503 means the writer cannot accept more mutations in this serving session.
Restart the service before retrying.

## Unavailable forms

Groundhog 0.3 does not implement SQL, joins, offset pagination, or arbitrary JSON-path filters.
Query is not available with the S3 event-log backend.

Groundhog also does not implement NDJSON ingest, `POST /v1/imports`, observation ingest, or a TCP
listener. Sending these routes or media types does not activate partial behavior.

## See also

[`serve`](/groundhog/commands#serve),
[configuration](/groundhog/references/configuration),
[events](/groundhog/concepts/events),
[getting started](/guides/getting-started)

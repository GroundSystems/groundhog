---
title: Groundhog HTTP API
description: HTTP transport, authentication, routes, limits, errors, and retry behavior.
---

## Name

`groundhog-http`: v1 client API over a Unix domain socket.

## Transport

The service speaks HTTP/1.1 over the Unix socket configured by `[server].socket`. It does not
listen on TCP.

HTTP/1.1 requires a `Host` header, but Groundhog ignores its value. With `curl`:

```sh
curl --unix-socket data/ground.sock http://ground/v1/catalog
```

Request and response bodies are UTF-8 JSON. A body request accepts `Content-Type:
application/json` or a missing content type. The optional `charset=utf-8` parameter is accepted.
Other media types, parameters, or any `Content-Encoding` return 415 before the body is read.

## Authentication

If `[server].token` is non-empty, every request must include:

```text
Authorization: Bearer <token>
```

A missing or mismatched token returns:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"error":"unauthorized"}
```

Authorization happens before routing, admission, or body reading. When the configured token is
empty, the authorization header is ignored.

## Current routes

| method | path | purpose |
|---|---|---|
| `POST` | `/v1/events` | Append an atomic JSON event batch. |
| `GET`, `HEAD` | `/v1/events` | Replay a coherent log snapshot. |
| `POST` | `/v1/query` | Run confined read-only SQL. |
| `GET`, `HEAD` | `/v1/catalog` | Read the published catalog. |

An unknown path returns 404. A known path with another method returns 405 and an `Allow` header.
`HEAD` returns the same status and headers as `GET` with no body.

## Error documents

Most errors use:

```json
{"error":"human-readable message"}
```

Per-event batch validation uses:

```json
{
  "errors": [
    {"index": 3, "error": "record_key empty"}
  ]
}
```

Clients should match HTTP status and document structure rather than message wording.

Repeated query parameters, duplicate JSON member names, and unknown body members are rejected.
Control envelopes are bounded at 1 MiB. JSON ingest has its own larger bound.

## `POST /v1/events`

Appends one atomic batch:

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

`v` defaults to 1 when omitted. `source` and `batch_id` are batch-level fields. A submitted event
has exactly `stream`, `record_key`, `kind`, optional `occurred_at`, and `payload`.

The batch is rejected whole if any event is invalid. Empty batches are invalid. Limits are
10,000 events and 32 MiB of encoded body.

### Idempotency

`(source, batch_id)` is reserved for the lifetime of the data directory. Groundhog computes a
canonical digest from the submitted content before assigning server fields.

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

An identical retry returns the original receipt with `status: "duplicate"` and writes nothing.
Reusing the key for different content returns 409 and writes nothing.

A successful ingest receipt means the batch is durable. A lost response leaves the client
uncertain; retrying identical content under the same key safely converges on one batch.

### Naming and bounds

- `source`, `stream`, and ordinary name-like values are bounded and source/stream names match
  `[a-z0-9_][a-z0-9_.-]*`;
- `record_key` and `batch_id` must be non-empty;
- source `system` is reserved;
- submitted batch IDs beginning with `groundhog/` are reserved; and
- `occurred_at`, when supplied, is UTC with a `Z` suffix.

See [Events](/concepts/events) for the full fixed event envelope.

## `GET /v1/events`

Replays authoritative history in increasing `event_id` order:

```text
GET /v1/events?after=<event_id>&source=stripe&stream=customers&kind=upserted&limit=1000
```

All parameters are optional and exact-match. `after` is exclusive. `limit` must be a positive
integer no greater than `[replay].max_limit`; omission uses `[replay].default_limit`.

Response:

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
  "snapshot_through_event_id": "..."
}
```

`last_event_id` is the last matching event returned and is omitted on an empty match. It is not
the progress cursor for a filtered subscription.

`next_after` is the position through which the request actually scanned. When the snapshot is
exhausted it advances to the snapshot frontier even if no event matched. Persist it for the next
poll so unrelated history cannot stall a filtered consumer.

`snapshot_through_event_id` is the coherent frontier captured for this request, or `null` for an
empty log.

## `POST /v1/query`

Executes one confined read-only statement against one pinned published warehouse generation:

```json
{
  "sql": "SELECT source, count(*) AS events FROM events GROUP BY source ORDER BY source, events",
  "format": "json",
  "limit": 10000,
  "timeout_secs": 30
}
```

`sql` is required. `format` defaults to `json`, the available result format. `limit` and
`timeout_secs` default to configuration and must be positive and within their configured maxima.

Success:

```json
{
  "columns": ["source", "events"],
  "rows": [["stripe", 42]],
  "truncated": false,
  "receipt": {
    "as_of_event_id": "...",
    "chain_head": "...",
    "groundhog_version": "0.1.0",
    "storage_schema_version": 1,
    "projections_hash": "..."
  }
}
```

The query boundary allows one `SELECT` or `WITH` statement over published relations. It rejects
mutations, multiple statements, file/network table functions, extension installation/loading,
attach/copy/import/export, secrets, shell access, mutating pragmas/settings, volatile functions,
and unproved order-dependent constructs.

A result cut by the server row limit requires a total top-level `ORDER BY`. The order must cover
all output columns; `ORDER BY ALL` is the simplest general form. Nested
`LIMIT` or `OFFSET` blocks require the same proof. Without a total order, an over-limit result is
rejected instead of returning an arbitrary subset.

Queries execute only against the last published generation. Events appended after its receipt
remain available through replay but are absent from SQL until `project` or `rebuild` publishes a
new frontier.

## `GET /v1/catalog`

Returns published stream-level metadata:

```text
GET /v1/catalog?source=stripe&stream=customers
```

Both narrowing parameters are optional. Response:

```json
{
  "receipt": {
    "as_of_event_id": "...",
    "chain_head": "...",
    "groundhog_version": "0.1.0",
    "storage_schema_version": 1,
    "projections_hash": "..."
  },
  "streams": [
    {
      "source": "stripe",
      "stream": "customers",
      "event_count": 42,
      "first_observed_at": "...",
      "last_observed_at": "...",
      "kinds": ["deleted", "upserted"]
    }
  ]
}
```

The receipt is from the same pinned warehouse generation as the stream list.

## Common status codes

| status | meaning |
|---:|---|
| 200 | Success, including a duplicate ingest receipt. |
| 400 | Invalid request, batch, replay cursor, query, or SQL. |
| 401 | Missing or incorrect configured bearer token. |
| 404 | Unknown route. |
| 405 | Unsupported method on a known route. |
| 408 | Query timeout completed and cancellation finished. |
| 409 | Batch ID was already committed with different content. |
| 413 | Request body or event count exceeded its bound. |
| 415 | Unsupported content type, parameter, or content encoding. |
| 429 | Bounded admission was unavailable; inspect `Retry-After`. |
| 503 | The writer is poisoned and must be reopened. |

A 429 rejected before mutation enqueue has written nothing and is retryable. Once mutation work
is enqueued, it is not abandoned because the client disconnects. A 503 means the writer cannot
accept further mutation until the service is closed and reopened through recovery.

## Unavailable forms

The binary does not implement NDJSON streaming ingest, `POST /v1/imports`, observation ingest, or Arrow
query results. Sending their media types, routes, or formats does not activate partial behavior.

## See also

[`serve`](/commands#serve),
[configuration](/references/configuration),
[events](/concepts/events),
[getting started](/guides/getting-started)

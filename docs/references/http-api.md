---
title: Groundhog HTTP API
description: Groundhog 0.2 transport, authentication, log routes, errors, and retry behavior.
---

<!-- generated-doc: GroundSystems/groundhog-src -->
> Source: [`GroundSystems/groundhog-src/docs-export/references/http-api.md`](https://github.com/GroundSystems/groundhog-src/blob/29b0fa4fc92fd4d4902533e4a714b1be97686eb9/docs-export/references/http-api.md) at [`29b0fa4fc92f`](https://github.com/GroundSystems/groundhog-src/commit/29b0fa4fc92fd4d4902533e4a714b1be97686eb9).
> Edit the source file. Do not edit this generated copy.


## Name

`groundhog-http`: the version 1 log API over a Unix domain socket.

Groundhog stores and serves the durable event log.
Applications build derived views from replay or follow.

## Transport

The service speaks HTTP/1.1 over the Unix socket configured by `[server].socket`.
It does not listen on TCP.

HTTP/1.1 requires a `Host` header, but Groundhog ignores its value.

```sh
curl --unix-socket data/ground.sock http://ground/v1/streams
```

Request and response bodies use UTF-8 JSON unless a follow response uses NDJSON.

A request body accepts `Content-Type: application/json` or no content type.
Groundhog accepts the optional `charset=utf-8` parameter.
Other parameters, media types, or content encodings return 415 before Groundhog reads the body.

## Authentication

If `[server].token` is not empty, every request needs:

```text
Authorization: Bearer <token>
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

An unknown path returns 404.
A known path with another method returns 405 and an `Allow` header.
`HEAD` returns the same status and headers as `GET` without a body.

`POST /v1/query` and `GET /v1/catalog` are not routes in Groundhog 0.2.
They return 404.

## Error documents

Errors use a stable code and a separate message:

```json
{
  "error": "invalid_replay_request",
  "message": "The request contains an invalid replay parameter."
}
```

Clients must match `error` and HTTP status.
They must not match `message` text.

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

Each submitted event has `stream`, `record_key`, `kind`, optional `occurred_at`, and `payload`.
Groundhog rejects the complete batch when any event is invalid.

A batch contains 1 through 10,000 events and no more than 32 MiB of encoded JSON.

### Idempotency

`(source, batch_id)` identifies one batch for the life of the data directory.
Groundhog computes a canonical digest before it assigns server fields.

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
Different content with the same key returns 409 and writes nothing.

A successful receipt means the complete batch is durable.
Retry identical content with the same key after a lost response.

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
  "snapshot_through_event_id": "..."
}
```

`last_event_id` is the last matching event and is absent for an empty result.
It is not the progress cursor for a filtered consumer.

`next_after` is the last position that the request conclusively scanned.
Persist it for the next finite poll.

`snapshot_through_event_id` is the coherent frontier captured for the request.
It is `null` only for an empty log.

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
- A `caught_up` record marks the end of the initial snapshot.
- An `end` record gives a terminal reason and the last delivered event ID.

Terminal reasons are `shutdown`, `writer_poisoned`, `session_closed`, `buffer_exceeded`, and `replay_failed`.
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

A successor can declare one retired predecessor in its first batch. The first submitted event uses
stream `groundhog.source_lineage`, kind `source_succeeded`, and the predecessor as its record key.
Its payload contains the predecessor source and exact retired frontier.

Groundhog returns `400 invalid_source_lineage` for a malformed or misplaced marker. It returns
`409 source_lineage_conflict` when the predecessor retirement or successor state conflicts.

## Common status codes

| status | meaning |
|---:|---|
| 200 | Success, including a duplicate ingest receipt. |
| 400 | Invalid request, batch, event, replay, stream, or lifecycle input. |
| 401 | Missing or incorrect bearer token. |
| 404 | Unknown route or unknown source for retirement. |
| 405 | Unsupported method on a known route. |
| 409 | Batch identity, stream frontier, retirement, or lineage conflict. |
| 413 | A body or event count exceeded its limit. |
| 415 | Unsupported content type, parameter, or content encoding. |
| 429 | Bounded admission was unavailable. Inspect `Retry-After`. |
| 503 | The writer cannot accept mutations until the service reopens it. |

A 429 rejected before mutation queue admission writes nothing and is retryable.
Queued mutations reach their real storage result after a client disconnects.

A 503 means the writer cannot accept more mutations in this serving session.
Restart the service before retrying.

## Unavailable forms

Groundhog 0.2 does not implement local SQL, `/v1/query`, or `/v1/catalog`.

It also does not implement NDJSON ingest, `POST /v1/imports`, observation ingest, or a TCP listener.
Sending these routes or media types does not activate partial behavior.

## See also

[`serve`](/commands#serve),
[configuration](/references/configuration),
[events](/concepts/events),
[getting started](/guides/getting-started)

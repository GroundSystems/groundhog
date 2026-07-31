---
title: Python SDK
description: Install and use groundhog-sdk 0.2 for ingest, replay, and stream enumeration.
---

<!-- generated-doc: GroundSystems/groundhog-sdk-python -->
> Source: [`GroundSystems/groundhog-sdk-python/docs-export/python.md`](https://github.com/GroundSystems/groundhog-sdk-python/blob/89f24881b7c2369fc752c1d83faa6a5507f0e891/docs-export/python.md) at [`89f24881b7c2`](https://github.com/GroundSystems/groundhog-sdk-python/commit/89f24881b7c2369fc752c1d83faa6a5507f0e891).
> Edit the source file. Do not edit this generated copy.


The `groundhog-sdk` package is the synchronous Python client for the Groundhog version 1 HTTP API.
Version 0.2 supports Unix sockets and HTTPS.

Each SDK operation maps to one public HTTP operation.
Groundhog remains responsible for durability, order, idempotency, and authoritative stream state.

The SDK does not provide local SQL or derived views.

## Requirements

- Python 3.10 or newer
- A running Groundhog 0.2 service
- Access to its Unix socket or HTTPS endpoint
- Its bearer token when authentication is active

The SDK does not install, start, stop, or supervise Groundhog.

## Installation

Install the 0.2 release from PyPI:

```sh
python -m pip install 'groundhog-sdk>=0.2,<0.3'
```

The PyPI distribution name is `groundhog-sdk`.
Python code imports `groundhog_sdk`.

## Connect through a Unix socket

```python
from groundhog_sdk import Ground

ground = Ground("unix:demo/data/ground.sock")
```

The SDK accepts absolute and relative socket paths:

```text
unix:/var/run/groundhog.sock
unix:demo/data/ground.sock
```

The default endpoint is `unix:data/ground.sock`.

## Connect through HTTPS

```python
from groundhog_sdk import Ground

ground = Ground(
    "https://groundhog.example.com",
    token="service-token",
)
```

The HTTPS transport uses standard certificate and hostname verification.
An endpoint can include a port and base path.

```text
https://groundhog.example.com:8443/service
```

Groundhog itself listens only on a Unix socket.
An operator-managed HTTPS service must forward the version 1 routes.

## Explicit transport settings

Use `TransportConfig` to keep the endpoint and timeout in one value:

```python
from groundhog_sdk import Ground, TransportConfig

transport = TransportConfig(
    "https://groundhog.example.com",
    timeout=10,
)
ground = Ground(transport=transport, token="service-token")
```

`Ground` also reads `GROUND_URL` and `GROUND_TOKEN`.
Explicit arguments take precedence over environment variables.

`max_retries` sets the number of attempts after the first request.
The default is 3.

The SDK retries connection failures and HTTP 429 responses.
Ingest also retries HTTP 503 responses with bounded exponential delays.

## Build events

The event constructors produce the connector-owned fields:

```python
from groundhog_sdk import deleted, native, upserted

created = upserted(
    "customers",
    "cus_123",
    {"id": "cus_123", "name": "Ada"},
    occurred_at="2026-07-14T16:30:00Z",
)

removed = deleted(
    "customers",
    "cus_456",
    {"id": "cus_456"},
)

paid = native(
    "invoices",
    "in_789",
    "invoice.paid",
    {"id": "in_789", "amount": 4200},
)
```

The SDK validates names, keys, kinds, times, payloads, finite numbers, Unicode, and nesting before sending.
Groundhog performs authoritative validation.

## Ingest an atomic batch

```python
receipt = ground.send(
    "stripe",
    [created],
    batch_id="stripe/customers/page-1",
)

print(receipt.status)
print(receipt.batch_digest)
print(receipt.events)
print(receipt.first_event_id)
print(receipt.last_event_id)
```

`send(source, events, batch_id)` maps to `POST /v1/events`.
A batch contains 1 through 10,000 events and no more than 32 MiB.

The SDK encodes the complete batch once before its first attempt.
A retry sends identical bytes with the same `(source, batch_id)`.

- `committed` means the request durably appended the batch.
- `duplicate` means identical content already committed.
- `IdempotencyConflict` means the key identifies different committed content.

Advance a source cursor only after a successful `BatchReceipt`.

## Replay events

```python
page = ground.events(
    after=None,
    source="stripe",
    stream="customers",
    kind="upserted",
    limit=1000,
)

for event in page.events:
    print(event["event_id"], event["record_key"], event["payload"])

cursor = page.next_after
```

`events()` maps to one finite `GET /v1/events` request.
It returns full events in authoritative `event_id` order.

Filters use exact matches and `after` is exclusive.
Persist `next_after` for the next finite request.

`EventPage` contains:

| field | meaning |
|---|---|
| `events` | Matching event objects. |
| `last_event_id` | The last matching event, or `None`. |
| `next_after` | Durable scan progress for the next request. |
| `snapshot_through_event_id` | The captured global log frontier. |

The 0.2 SDK returns one finite page per call.
It does not provide a follow iterator or persistent cursor storage.

Use the HTTP API directly when a Python application needs continuous follow.

## Enumerate streams

```python
page = ground.streams(source="stripe", limit=100)

for item in page.streams:
    print(
        item.source,
        item.stream,
        item.event_count,
        item.frontier_event_id,
    )
```

`streams()` maps to `GET /v1/streams`.
It returns typed `Stream` values in a `StreamPage`.

Each row reports authoritative state from the durable log.
It does not report a derived catalog snapshot.

For another page, use one anchored snapshot:

```python
if page.next_after is not None:
    next_page = ground.streams(
        source="stripe",
        after=page.next_after,
        through=page.snapshot_through_event_id,
        limit=100,
    )
```

Use the same source filter on each page.
`after` requires the first page's `snapshot_through_event_id` as `through`.

## Build derived views

Groundhog stores and serves the durable event log.
Applications build their own derived views from replay.

A Python consumer normally applies each event and saves its event ID in the same database transaction.
It can rebuild the view by replaying the log from the start.

The SDK does not include a database adapter, SQL engine, or current-state model.

## Errors

All SDK exceptions derive from `GroundError`.
Remote errors expose these attributes:

| attribute | meaning |
|---|---|
| `status` | The HTTP status. |
| `code` | The stable server error code. |
| `message` | The descriptive error text. |
| `body` | The complete decoded response. |

Use `code`, not `message`, for program control.
The server can change descriptive text without changing its contract.

| exception | meaning |
|---|---|
| `ValidationError` | Local validation failed, or Groundhog returned HTTP 400 or 413. |
| `IdempotencyConflict` | The batch key identifies different committed content. |
| `ConnectionError` | No complete response arrived within the configured attempts. |
| `GroundError` | Another server failure or an invalid server response. |

`ValidationError.errors` contains indexed event errors when the server provides them.
Local errors and responses from old servers can have `code` set to `None`.

## Current 0.2 surface

The package exports:

```text
Ground, TransportConfig
upserted, deleted, native
BatchReceipt, EventPage, Stream, StreamPage
GroundError, ValidationError, IdempotencyConflict, ConnectionError
PROTOCOL_VERSION
```

Version 0.2 removes `Ground.query()`, `Ground.catalog()`, `QueryResult`, `CatalogResult`, `SnapshotReceipt`, and `QueryError`.

The package does not include follow, persistent cursors, async parity, connector management, or Groundhog process supervision.

---
title: Events
description: Understand the event data that connectors submit and clients consume.
---

Groundhog stores changes from connected systems as one ordered event history. Connectors submit
events; clients replay or query them later.

Groundhog records what it receives. It does not fetch from source systems or claim knowledge of
changes that a connector did not deliver.

## What a connector submits

Events are submitted in a batch with a shared source and batch ID:

```json
{
  "v": 1,
  "batch_id": "delivery-123",
  "source": "example",
  "events": [
    {
      "stream": "contacts",
      "record_key": "contact-42",
      "kind": "upserted",
      "occurred_at": "2026-07-14T16:30:00Z",
      "payload": {"name": "Ada"}
    }
  ]
}
```

The batch is atomic: either every event is accepted or none is written.

Each submitted event contains:

| field | meaning |
|---|---|
| `stream` | Collection within the source, such as `customers` or `invoices`. |
| `record_key` | Identity of the record within that source. |
| `kind` | `upserted`, `deleted`, or a source-specific event kind. |
| `occurred_at` | Optional time reported by the source. |
| `payload` | The JSON value supplied by the connector. |

## What Groundhog adds

Committed events returned by replay and exposed in SQL include:

| field | meaning |
|---|---|
| `event_id` | Immutable identity and position in Groundhog history. |
| `source` | Connected system that supplied the batch. |
| `stream` | Collection within the source. |
| `record_key` | Source-scoped record identity. |
| `kind` | Record-state or source-specific event kind. |
| `occurred_at` | Optional source time. |
| `observed_at` | Time Groundhog received the event. |
| `payload` | Submitted JSON value. |
| `content_hash` | Commitment identifying the submitted payload. |
| `batch_id` | Idempotency ID of the batch that delivered the event. |
| `event_hash` | Commitment identifying the complete event. |

## Ordering and timestamps

Increasing `event_id` is the authoritative history order. Replay returns events in that order.

`occurred_at` is source-provided data and may be missing or out of order. It never changes the
event's position in Groundhog history. Use `event_id` for replay cursors and processing order.

SQL relations do not have an implicit order. Use `ORDER BY event_id` when event order matters.

## Event kinds

`upserted` says the named record exists with the supplied payload. `deleted` says the record no
longer exists. Other kinds represent source-specific occurrences and do not implicitly replace
record state.

The binary does not publish a ready-made current-state relation. Consumers that need current
state derive it from the event history.

## Idempotent batches

The pair `(source, batch_id)` identifies one batch for the life of the data directory.

- A new ID commits the batch and returns `status: "committed"`.
- Retrying the same ID with identical content returns `status: "duplicate"` and the original
  receipt.
- Reusing the same ID for different content returns HTTP 409 and writes nothing.

Use a stable delivery, webhook, export, or sync-run ID. If a response is lost, retry the identical
batch with the same ID. Creating a new ID for the retry can duplicate history.

## Names, times, and limits

- `source` and `stream` match `[a-z0-9_][a-z0-9_.-]*` and are at most 128 UTF-8 bytes.
- `kind` is non-empty and at most 128 bytes.
- `record_key` is non-empty and at most 1,024 bytes.
- `batch_id` is non-empty and at most 256 bytes.
- Source `system` and batch IDs beginning with `groundhog/` are reserved.
- `occurred_at` uses UTC with a `Z` suffix when provided.
- A JSON batch contains 1–10,000 events and is at most 32 MiB.

## See also

[HTTP API](/references/http-api),
[Storage](/concepts/storage),
[Getting started](/guides/getting-started)

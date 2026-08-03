---
title: Events
description: Understand the event data that connectors submit and consumers process.
---

Groundhog stores changes from connected systems as one ordered event history.
Connectors submit events.
Consumers replay events, follow new commits, and build their own derived views.

Groundhog records submitted changes.
It does not fetch from source systems or infer changes that a connector did not submit.

## What a connector submits

Events use a batch with one source and batch ID:

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

The batch is atomic.
Groundhog accepts every event or writes none of them.

Each submitted event contains:

| field | meaning |
|---|---|
| `stream` | A collection in the source, such as `customers` or `invoices`. |
| `record_key` | The record identity in that source. |
| `kind` | `upserted`, `deleted`, or a source-specific event kind. |
| `occurred_at` | Optional time reported by the source. |
| `payload` | The JSON value supplied by the connector. |

## What Groundhog adds

Replay and follow return committed events with these fields:

| field | meaning |
|---|---|
| `event_id` | Immutable identity and position in Groundhog history. |
| `source` | The connected system that supplied the batch. |
| `stream` | The collection in the source. |
| `record_key` | The source-scoped record identity. |
| `kind` | The submitted event kind. |
| `occurred_at` | Optional source time. |
| `observed_at` | The batch admission time. All events in one batch use this time. |
| `payload` | The submitted JSON value. |
| `content_hash` | A commitment to the submitted payload. |
| `batch_id` | The idempotency ID for the submitted batch. |
| `event_hash` | A commitment to the complete event. |

## Ordering and timestamps

Increasing `event_id` is the authoritative history order.
Replay and follow return events in this order.

`occurred_at` is source data and can be missing or out of order.
It never changes the event's position in Groundhog history.

Consumers must use `event_id` for cursors and processing order.

## Event kinds and derived views

`upserted` states that the named record exists with the supplied payload.
`deleted` states that the record no longer exists.

Other kinds describe source-specific occurrences.
They do not replace record state unless a consumer defines that behavior.

Groundhog does not provide a current-state relation or local SQL.
Applications build current state, indexes, reports, and other derived views from replay or follow.

## Idempotent batches

The pair `(source, batch_id)` identifies one batch for the life of the data directory.

- A new key commits the batch and returns `status: "committed"`.
- A retry with the same committed event content returns `status: "duplicate"` and the original
  receipt.
- Different content with the same key returns HTTP 409 and writes nothing.

Use a stable delivery, webhook, export, or synchronization ID.
Retry identical content with the same ID after a lost response.

## Conditional append

A batch can require an expected frontier for one stream.
The `stream_precondition` field names the stream and its expected latest event ID.
Every event in the batch must use the named stream.

Set `expected_frontier` to `null` when the stream must have no committed events.
A mismatch returns HTTP 409 and commits nothing.

A matching retry returns its original receipt before Groundhog checks the precondition again.
The precondition is not part of the batch content identity.

## Source lifecycle

Groundhog can permanently retire a source through `POST /v1/sources/retire`.
A retired source keeps its complete history but refuses new batches.
Groundhog records the retirement as one ordered event from the reserved `system` source.
It uses stream `groundhog.source_lifecycle` and kind `source_retired`.
Its payload records the retired source and that source's final event ID.

A new source can declare one retired predecessor in its first batch. The first event must use
stream `groundhog.source_lineage`, kind `source_succeeded`, and the predecessor as its record key.

The lineage payload contains `v`, `predecessor_source`, and `predecessor_final_frontier`. The
predecessor must have a retirement event at that exact frontier. Groundhog rejects a lineage
marker after the successor already has committed events.

## Names, times, and limits

- `source` and `stream` match `[a-z0-9_][a-z0-9_.-]*` and use at most 128 UTF-8 bytes.
- `kind` is not empty and uses at most 128 bytes.
- `record_key` is not empty and uses at most 1,024 bytes.
- `batch_id` is not empty and uses at most 256 bytes.
- Groundhog reserves source `system` and batch IDs that start with `groundhog/`.
- `occurred_at` uses `YYYY-MM-DDTHH:MM:SSZ` when it has no fractional seconds.
- Fractional seconds use a decimal point followed by one through nine digits before `Z`.
- Groundhog rejects numeric UTC offsets, leap seconds, and invalid calendar dates.
- A JSON batch contains 1 through 10,000 events and uses at most 32 MiB.

## JSON and hash rules

Groundhog rejects duplicate JSON object members, malformed Unicode, non-finite numbers, and
integer aliases that lose precision. Payloads can contain at most 128 nested array or object
containers.

Groundhog canonicalizes accepted JSON with RFC 8785. `content_hash` is SHA-256 over the canonical
payload bytes. `event_hash` is SHA-256 over the canonical committed event envelope without the
payload.

The event envelope contains `batch_id`, `content_hash`, `event_id`, `kind`, `observed_at`,
`record_key`, `source`, and `stream`. It contains `occurred_at` only when the submitted event has
that field.

Groundhog computes `batch_digest` from the version, source, ordered event identity fields, and
content hashes. The digest excludes `batch_id` and `stream_precondition`.
The pair `(source, batch_id)` supplies the separate idempotency key.

## See also

[HTTP API](/groundhog/references/http-api),
[Storage](/groundhog/concepts/storage),
[Getting started](/guides/getting-started)

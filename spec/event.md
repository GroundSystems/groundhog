# Event Contract

This document defines contract version 1 event values and JSON processing rules.

## JSON input

An HTTP request body MUST contain valid UTF-8. The body MUST contain exactly one JSON value.

Groundhog MUST reject duplicate object member names at every depth. Escaped and unescaped forms of
the same member name are duplicates.

Groundhog MUST reject malformed Unicode. This rule includes unpaired UTF-16 surrogate escapes.

Groundhog interprets JSON numbers as finite IEEE 754 binary64 values. Groundhog MUST reject a
number that cannot produce a finite binary64 value.

Groundhog MUST reject a precision-losing integer alias. An integer literal can exceed `2^53 - 1`
in magnitude only in one case. Its spelling must equal the RFC 8785 binary64 spelling.

Other decimal values use binary64 semantics. Groundhog uses RFC 8785 JSON Canonicalization Scheme
rules for member order, number serialization, string escaping, and UTF-8 output.

A payload can contain at most 128 array or object containers on one root-to-leaf path. A root
container counts as one. A scalar payload has a depth of zero.

## Identifier rules

Groundhog measures identifier limits in UTF-8 bytes. It MUST NOT truncate, replace, or hash an
identifier to satisfy a limit.

| Identifier | Required form | Maximum UTF-8 bytes |
| --- | --- | ---: |
| `source` | `[a-z0-9_][a-z0-9_.-]*` | 128 |
| `stream` | `[a-z0-9_][a-z0-9_.-]*` | 128 |
| `record_key` | non-empty JSON string | 1,024 |
| `kind` | non-empty JSON string | 128 |
| `batch_id` | non-empty JSON string | 256 |

Clients MUST NOT submit the source `system`. Groundhog reserves this source for its own events.

Clients MUST NOT submit a `batch_id` that starts with `groundhog/`. Groundhog reserves this prefix
for its own batches.

`record_key` identifies a record within one source. Groundhog does not assign cross-source meaning
to this value.

The kinds `upserted` and `deleted` have their literal meanings. A connector MAY use another
non-empty kind for a source-native event.

## Submitted event

A submitted event contains these members:

| Member | Type | Requirement |
| --- | --- | --- |
| `stream` | string | required |
| `record_key` | string | required |
| `kind` | string | required |
| `occurred_at` | string | optional |
| `payload` | any JSON value | required |

The submitted event is a closed object. Groundhog MUST reject an unknown member.

`occurred_at` MUST use `YYYY-MM-DDTHH:MM:SS(.d{1,9})?Z`. The value MUST name a real UTC calendar
instant. Numeric offsets and leap seconds are invalid. Groundhog stores the accepted value without
changing its spelling.

## Committed event

Groundhog adds fields to make the committed event in [`schemas/event.schema.json`](schemas/event.schema.json).

`event_id` is a canonical, hyphenated RFC-variant UUIDv7. Its byte order defines committed log
order. Groundhog MUST assign an ID after the durable frontier.

`observed_at` is the Groundhog receipt time. It uses `YYYY-MM-DDTHH:MM:SS.dddZ` in UTC.

`payload` is the submitted JSON value after RFC 8785 canonicalization. A response renders it as a
JSON value, not as a quoted JSON string.

`content_hash` is lowercase hexadecimal SHA-256 over the canonical payload UTF-8 bytes.

`batch_id` identifies the accepted batch. All events in one client batch have the same `source`
and `batch_id`.

`event_hash` is lowercase hexadecimal SHA-256 over the RFC 8785 canonical event envelope. The
envelope contains `batch_id`, `content_hash`, `event_id`, `kind`, `observed_at`, `record_key`,
`source`, and `stream`. It contains `occurred_at` only when the submitted event contained it. The
envelope does not contain `payload`.

The fixed event fields evolve additively. A later contract version MUST NOT change the meaning of
an existing field.

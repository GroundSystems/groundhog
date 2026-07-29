# Stream Enumeration Contract

This document defines `GET /v1/streams` for contract version 1.

## Request

The request accepts these optional query parameters:

| Parameter | Meaning |
| --- | --- |
| `source` | exact source match |
| `after` | exclusive `source/stream` cursor |
| `through` | inclusive event frontier anchor |
| `limit` | maximum returned rows |

Each parameter can occur at most once. Unknown or repeated parameters return HTTP 400.

`source` MUST satisfy the identifier rules in [`event.md`](event.md).

`after` contains a valid source, one `/`, and a valid stream. Source and stream names cannot contain
`/`, so the decoded cursor is unambiguous.

Clients SHOULD percent-encode the `/` when their HTTP library requires it. The comparison is
exclusive and uses source order followed by stream order.

`through` MUST be a canonical UUIDv7 that exists as a committed event. Groundhog rejects an
unavailable anchor with HTTP 400.

`limit` MUST be an integer from 1 through 1,000. The default is 100.

An `after` cursor requires `through`. Groundhog MUST reject `after` without `through`.

## Enumeration snapshot

Groundhog reads committed log state directly. It MUST NOT use the local warehouse projection.

Without `through`, Groundhog captures the current durable frontier. With `through`, Groundhog uses
that inclusive historical frontier.

Groundhog MUST ignore events after the selected frontier. Uncommitted bytes MUST NOT affect rows or
counts.

For each matching `(source, stream)` pair, Groundhog computes the committed event count and latest
event ID at the selected frontier.

The result order is lexicographic by `source`, then by `stream`. Groundhog applies `after` in this
order after it computes all matching summaries.

## Response

A successful response uses HTTP 200. It MUST match
[`schemas/streams-response.schema.json`](schemas/streams-response.schema.json).

`frontier_event_id` is the latest committed event for the row at the selected frontier.
`event_count` is the number of committed events for the row through that frontier.

`snapshot_through_event_id` is the selected global frontier. It remains independent of an optional
source filter.

The snapshot frontier is null only for an empty log. A source filter with no matches still returns
the non-null selected global frontier.

`next_after` is the last returned `source/stream` cursor when more rows exist. It is null when no
more row exists at the selected frontier.

## Anchored pagination

For the first page, the client normally omits `after` and `through`. The response selects one
durable frontier.

For each later page, the client MUST send the same source filter. It MUST also send these values:

- `after=<next_after>` from the preceding page
- `through=<snapshot_through_event_id>` from the first page

The anchor excludes later appends. All pages with the same filters and anchor reconstruct one
logical enumeration snapshot.

The anchor does not require server-side cursor state. It remains valid after a seal or process
restart while the committed event remains available.

Rows contain no payloads, paths, integrity claims, or liveness status. Local catalog state is a
separate projection view and can lag this durable enumeration.

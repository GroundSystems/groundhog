# Finite Replay Contract

This document defines finite `GET /v1/events` responses for contract version 1.

## Request

The request accepts these optional query parameters:

| Parameter | Meaning |
| --- | --- |
| `source` | exact source match |
| `stream` | exact stream match |
| `record_key` | exact record-key match |
| `kind` | exact kind match |
| `after` | exclusive event ID cursor |
| `limit` | maximum returned events |

Each parameter can occur at most once. Unknown or repeated parameters return HTTP 400.

Filters compare decoded UTF-8 strings with exact equality. All present filters combine with logical
AND.

`record_key` MUST be non-empty and at most 1,024 UTF-8 bytes. `after` MUST be a canonical UUIDv7.

`limit` MUST be a positive decimal integer. The local default is 1,000, and the local maximum is
100,000. An implementation MUST reject a value above its published maximum instead of reducing it.

The shared contract defines one finite JSON response. A held or streaming response is an extension
and is not part of this contract.

## One-request snapshot

Groundhog MUST capture one coherent committed log snapshot for each request. The returned events,
scan progress, and snapshot frontier MUST come from that one capture.

Groundhog MUST exclude uncommitted tail bytes. Sealing or rotation during the request MUST NOT
change the captured event sequence.

Groundhog scans in increasing `event_id` order. It considers only events strictly after `after`.

Groundhog MAY stop at the requested event count or an operational response-size bound. It MUST
return at least one matching event before a size bound stops a non-empty result.

## Response

A successful response uses HTTP 200. It MUST match
[`schemas/replay-response.schema.json`](schemas/replay-response.schema.json).

`events` contains matching committed events in increasing `event_id` order.

`last_event_id` is the last returned event ID. Groundhog MUST omit this member when `events` is
empty.

`snapshot_through_event_id` is the captured durable frontier. It is null only when the captured log
is empty.

`next_after` reports the last position that this request conclusively scanned. It is not a claim
about a later request.

If a count or size bound stops the scan, `next_after` equals `last_event_id`. The request has not
proved whether a later matching event exists in its capture.

If the scan exhausts the capture, `next_after` advances to `snapshot_through_event_id`. An existing
`after` value at or beyond that frontier remains unchanged.

An empty filtered result can therefore advance `next_after` across unrelated events. `next_after`
is null only when both the captured log and `after` are absent.

## Continuation

A client MAY continue with the same filters and `after=<next_after>`. The next request captures its
own coherent snapshot.

The replay endpoint has no `through` anchor in contract version 1. The client cannot pin later
requests to the first response's `snapshot_through_event_id`.

Multiple finite responses do not form one snapshot. A continuation can include events that commit
after the earlier response.

The client MUST NOT infer snapshot exhaustion from `events.length < limit`. An operational size
bound can stop a response before the count limit.

Invalid parameters return HTTP 400. Unavailable admission returns HTTP 429. Server failures use the
error contract in [`errors.md`](errors.md).

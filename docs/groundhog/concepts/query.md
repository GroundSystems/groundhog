---
title: Query and Catalog
description: Enable and use immutable indexed Query snapshots in Groundhog 0.3.
---

Groundhog Query reads typed relations from one immutable published snapshot. The durable event log
remains the authoritative record. Query state is derived local data and can be rebuilt from the log.

Groundhog does not accept SQL. Clients send closed version 1 JSON objects to `POST /v1/query`.
Catalog describes the relations, fields, primary keys, and declared indexes available to those
requests.

## Current release scope

The current Groundhog 0.3 binary has these limits:

- Query runs only with `data.backend = "local"`.
- Query requires a non-empty `[server].token`.
- Query exposes `groundhog.events` and the complete Agent Operations version 1 relation pack. A
  deployment cannot select a subset.
- Projected relations support row selection, keyset cursors, grouped `count`, and numeric `sum`.
- `groundhog.events` supports row selection, keyset cursors, and `count` with or without
  `group_by`.
- The event index and the projected relations catch up during startup. The projection worker
  then publishes new event and projected snapshots during the serving session.
- Query does not support joins, offsets, arbitrary payload-path filters, SQL, or the S3 event-log
  backend.

## Enable Query

`groundhog init` for the local backend writes a disabled Query section. Enable the service with
explicit storage and authentication:

```toml
[server]
socket = "data/ground.sock"
token = "replace-with-a-secret"

[query]
enabled = true
backend = "local"
data_dir = "data/query"
```

`query.data_dir` must not be the data directory. It must not contain or be inside the log directory.
Groundhog creates the directory when it starts Query. This directory does not replace a durable log
backup.

When Query is disabled, the Query, Catalog, and projection-status routes are absent.
When Query is enabled, these routes require the configured bearer token.

## Inspect Catalog

List relation metadata:

```sh
groundhog catalog --config ./instance/groundhog.toml
```

Read one canonical relation name:

```sh
groundhog catalog groundhog.events --config ./instance/groundhog.toml
```

The equivalent HTTP routes are:

```text
GET  /v1/catalog
HEAD /v1/catalog
GET  /v1/catalog/relations/groundhog.events
HEAD /v1/catalog/relations/groundhog.events
```

Catalog reads snapshot metadata. It does not scan relation rows. Each response contains the same
query snapshot receipt format used by Query responses.

## Inspect projection status

Read the current snapshot and worker freshness for one canonical projection:

```text
GET  /v1/projections/agent_operations/status
HEAD /v1/projections/agent_operations/status
```

Groundhog 0.3 publishes two projections. `agent_operations` carries the Agent Operations version 1
pack. `groundhog_events` carries the built-in `groundhog.events` relation.

The response includes the projection name and version, the immutable Query snapshot receipt,
freshness relative to the current event-log frontier, cursor retention, and compaction.

Freshness reports `current`, `catching_up`, or `failed`, the log frontier event count the lag is
measured against, the event lag, and a failure message when the projection has failed. The
`groundhog_events` projection never reports `failed`.

Cursor retention reports the retained snapshot count and the unique retained bytes. Compaction
reports the delta-compaction phase, the completed and failed run counts, the last completed run,
and the last failure. Both describe the whole Query service, not the requested projection.

The route returns `404 not_found` for a name that is not a canonical projection name and for a name
that no relation projects. It returns `503 query_unavailable` while the service has not published
its first Query snapshot.

## Query event rows

This request matches the committed
[`event-row-query.json`](https://github.com/GroundSystems/groundhog/blob/main/verify/conformance/fixtures/query-v1/valid/event-row-query.json)
OpenAPI fixture:

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

Save the request as `query.json`, then send the exact bytes:

```sh
groundhog query query.json --config ./instance/groundhog.toml
```

Omit the file or use `-` to read standard input:

```sh
groundhog query --config ./instance/groundhog.toml < query.json
groundhog query - --config ./instance/groundhog.toml < query.json
```

The CLI writes the server JSON body to standard output without reformatting it. It returns exit code
0 for a 2xx status and exit code 1 for a server or transport error. For an HTTP error, the stable
JSON error remains on standard output and the status appears in the standard-error diagnostic.

## Relation fields and JSON encodings

`groundhog.events` exposes these fields:

| field | type | nullable |
|---|---|---:|
| `event_id` | `uuid` | no |
| `source` | `utf8` | no |
| `stream` | `utf8` | no |
| `record_key` | `utf8` | no |
| `kind` | `utf8` | no |
| `observed_at` | `timestamp_us_utc` | no |
| `occurred_at` | `utf8` | yes |
| `batch_id` | `utf8` | no |
| `payload` | `json` | no |
| `content_hash` | `utf8` | no |
| `event_hash` | `utf8` | no |

Query encodes `i64` and `u64` values as canonical decimal strings. It encodes finite `f64` values as
JSON numbers. UUID values use canonical lowercase text. `timestamp_us_utc` values use UTC text with
exactly six fractional digits. JSON fields can be selected, but Query does not filter or order by
JSON content.

## Filters and order

The version 1 request schema defines these filter operations:

| class | operations |
|---|---|
| Boolean | `and`, `or`, `not` |
| Comparison | `eq`, `not_eq`, `lt`, `lte`, `gt`, `gte` |
| Set | `in`, `not_in` |
| List | `contains`, `contains_any` |
| Null | `is_null`, `is_not_null` |

Filter values must match the relation field type. Groundhog performs no implicit conversion.
Strings use byte-exact, case-sensitive comparison.

The planner requires a declared index for bounded candidate selection or ordering. It returns
`index_required` when no declared access path satisfies the request. For `groundhog.events`, use:

- exact filters on `source`, `stream`, `record_key`, or `kind`
- `eq` or `in` on `event_id`
- `eq`, `in`, or range filters on `observed_at`
- `event_id` ascending or descending order
- `observed_at, event_id` ascending or descending order.

An omitted `order_by` uses primary-key order, which is ascending `event_id` for this relation.
The built-in event reader examines at most 10,000 indexed event IDs in one query. A larger candidate
set returns `query_limit_exceeded`, even when `scan_rows_per_request` has a larger value.

## Single and multi-query envelopes

A request contains exactly one of `query` or `queries`. The single form names its result `query`.
The multi form contains 1 through 16 objects with distinct names:

```json
{
  "v": 1,
  "consistency": {"mode": "published"},
  "queries": [
    {
      "name": "stripe_events",
      "query": {
        "relation": "groundhog.events",
        "select": ["event_id", "kind"],
        "filter": {"op": "eq", "field": "source", "value": "stripe"},
        "limit": 100
      }
    },
    {
      "name": "deletions",
      "query": {
        "relation": "groundhog.events",
        "select": ["event_id", "source", "record_key"],
        "filter": {"op": "eq", "field": "kind", "value": "deleted"},
        "limit": 100
      }
    }
  ]
}
```

Groundhog pins one snapshot for the complete request. It returns all results or one error. It does
not return a successful partial multi-query result.

## Consistency and receipts

`published` selects the current valid Query snapshot:

```json
{"mode": "published"}
```

`at_least` validates an event snapshot receipt and waits for a published Query snapshot whose
cumulative event count includes that receipt:

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

A chain or frontier mismatch returns `frontier_chain_mismatch`. An unmet valid frontier returns
`projection_frontier_timeout` after the requested wait. The publication worker can satisfy a later
valid receipt during the same serving session. `wait_timeout_ms` cannot exceed the configured
`max_timeout_ms` value.

Every successful Query response includes:

- `query_id`, which identifies the operation
- `snapshot.snapshot_id`, which identifies the immutable query manifest
- the exact event frontier ID, cumulative count, and chain head
- projection and schema version maps
- named results with columns, row arrays, and execution statistics.

The receipt identifies the input snapshot. It is not a result-content hash.

## Cursor contract

The version 1 result has `has_more` and `next_cursor`. A continuation sends the opaque cursor as the
relation query's `after` value. Signed cursors bind the query, relation schema,
selected snapshot, last ordered key, authorization scope, and expiry. A continuation reads the
cursor's original immutable snapshot. A changed query, schema, order, bearer-token scope, expired
cursor, or unavailable snapshot fails without executing against another snapshot.

## Aggregate contract

The version 1 schema defines grouped `count` and numeric `sum`. The validated request structure is in
[`aggregation-query.json`](https://github.com/GroundSystems/groundhog/blob/main/verify/conformance/fixtures/query-v1/valid/aggregation-query.json).
That fixture uses `agents.runs_current` from the bundled Agent Operations projection pack.

`group_by` lists output key fields. Each measure has a distinct output `name`. `count` produces a
`u64`, which JSON encodes as a decimal string. `sum` accepts `i64`, `u64`, or finite `f64` fields and
preserves that type. A sum with no non-null inputs is null. Aggregate `order_by` can reference a
group field or measure name. Grouped aggregates do not accept `after`.

Projected relations support grouped `count` and numeric `sum`.
The `groundhog.events` relation supports `count` with or without `group_by`. Every field it declares
is a UUID, string, timestamp, or JSON field, so it has no numeric field that can supply a `sum`
measure. A `sum` over a `groundhog.events` field returns `400 invalid_query`.

A `groundhog.events` aggregate reads its whole matching input in one request. An input larger than
the remaining scan-row budget returns `422 query_limit_exceeded` rather than a partial aggregate.

An aggregate `limit` truncates the completed groups. A truncated aggregate reports no cursor and no
further pages, so a limit below the group count discards the remaining groups.

## See also

[HTTP API](/groundhog/references/http-api),
[Configuration](/groundhog/references/configuration),
[CLI commands](/groundhog/commands),
[Events](/groundhog/concepts/events)

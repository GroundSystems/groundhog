---
title: Configuration
description: All fields accepted by Groundhog 0.3 in groundhog.toml.
---

Groundhog reads one TOML file for each deployment.
The default path is `./groundhog.toml`.

Pass another path with the global `--config <PATH>` option.
Relative paths in the file resolve against the file's directory.

`serve`, `seal`, `verify`, `query`, and `catalog` validate configuration before they open deployment
data, locks, or sockets. Unknown sections and keys are errors.

## Generated configuration

`groundhog init` for the local backend writes this file:

```toml
[data]
dir = "./data"

[security]
mode = "open"              # open | governed | locked — this build serves only "open"

[integrity]
anchor = "none"   # this binary supports only unsigned local chain heads

[server]
socket = "data/ground.sock"   # the binary's only transport
token = ""                    # empty = no auth (local development)

[replay]
default_limit = 1000
max_limit     = 100000

[query]
enabled = false
```

## `[data]`

### `backend`

The durable storage backend. Accepted values are `local` and `s3`.
Default: `local`.

An S3 deployment uses this form:

```toml
[data]
backend = "s3"

[data.s3]
bucket = "company-groundhog"
region = "us-west-2"
prefix = "groundhog/production"
```

The S3 backend requires all three fields. The prefix cannot be empty, start or end with `/`,
contain an empty component, contain `.` or `..` components, or exceed the S3 key budget.
The configuration does not accept credentials or custom endpoints. Groundhog uses the standard AWS
credential provider chain.

`data.dir` is invalid when `backend = "s3"`. `[data.s3]` is invalid for the local backend.

### `dir`

The directory that contains Groundhog data.
Default: `./data`.

The durable log is `<dir>/log/`.
Groundhog 0.3 does not use a warehouse path.

For S3 deployments, the local `data/scratch/` directory is disposable. It is not authoritative and
can be empty when the process starts.

Deleting the complete local deployment directory does not delete acknowledged S3 mutations. Run
`groundhog init` again with the exact bucket, region, and prefix to authenticate and reattach. Do not
change any of the three location fields during reattachment.

## `[security]`

### `mode`

The configured security contract.
Default: `open`.

Accepted names are `open`, `governed`, and `locked`.
Groundhog 0.3 serves only `open`.
It refuses other values with exit code 4 before it opens deployment state.

## `[integrity]`

### `anchor`

The configured chain-head anchoring contract.
Default: `none`.

Accepted names are `none`, `signed`, `mirrored`, and `witnessed`.
`serve`, `seal`, and `verify --chain` support only `none`.
They refuse each non-`none` mode with exit code 4.
Plain `verify` checks storage without enforcing this field.

## `[server]`

### `socket`

The Unix domain socket used by `serve`.
Default: `data/ground.sock`.

The service does not listen on TCP.
Clients need filesystem access to this socket.

### `token`

The bearer token required for every HTTP request.
Default: an empty string.

An empty token disables HTTP authentication.
A non-empty token requires this header:

```text
Authorization: Bearer <token>
```

The file stores the token as plaintext TOML.
Restrict file permissions and do not commit secrets to source control.
The token must contain 1 through 4096 visible ASCII bytes without spaces. Empty still disables
authentication when Query is disabled.

## `[replay]`

### `default_limit`

The matching-event limit used when finite replay omits `limit`.
Default: `1000`.

### `max_limit`

The largest accepted finite replay `limit`.
Default: `100000`.

Both values must be positive.
`default_limit` cannot exceed `max_limit`.

Follow mode uses these values as page limits within one open response.
The limit does not end the follow response.

## `[query]`

Query is disabled by default. The disabled form needs only:

```toml
[query]
enabled = false
```

The current binary enables Query only for a local event log. An enabled Query service exposes
`groundhog.events` and the complete Agent Operations version 1 relation pack. The relation set is
fixed. A deployment cannot select a subset. Use this form to enable Query:

```toml
[data]
backend = "local"
dir = "./data"

[server]
socket = "data/ground.sock"
token = "replace-with-a-secret"

[query]
enabled = true
backend = "local"
data_dir = "data/query"
```

Enabling Query requires all of these conditions:

- `[data].backend` is `local`
- `query.backend` is `local`
- `[server].token` is not empty
- `query.data_dir` is present, is not the data directory, and does not overlap the log directory.

Relative `data_dir` values resolve against the configuration file. The directory can be absent
before startup, but an existing path must be a real directory and not a symbolic link.

### Query state rebuilds

Groundhog compares the fixed relation schema versions and projection versions with the current Query
snapshot during startup. A difference starts a complete rebuild in an isolated directory. A binary
upgrade that changes a relation schema is the usual cause.

Groundhog validates the rebuilt event index, projection state, Catalog metadata, and event receipt.
It then imports the immutable objects and replaces `CURRENT` once. A rebuild error leaves the prior
snapshot current. Existing snapshot pins remain valid.

### Query limit fields

All Query limit values are positive integers. Each value has the listed default and inclusive
configuration maximum:

| field | default | maximum | purpose |
|---|---:|---:|---|
| `cursor_lifetime_secs` | 900 | 900 | Signed projected-relation cursor expiry. |
| `max_pinned_snapshots` | 128 | 128 | Snapshots retained by projected-relation cursors. |
| `max_pinned_bytes` | 10,737,418,240 | 10,737,418,240 | Bytes retained by projected-relation cursor snapshots. |
| `concurrent_requests` | 16 | 16 | Query requests admitted before body reads. |
| `executing_requests` | 4 | 4 | Query executions admitted after parsing. |
| `consistency_waiters` | 128 | 128 | Concurrent `at_least` waits. |
| `request_body_bytes` | 1,048,576 | 1,048,576 | Query request ceiling. |
| `response_body_bytes` | 67,108,864 | 67,108,864 | Query response ceiling. |
| `default_page_rows` | 100 | 10,000 | Row limit when a request omits `limit`. |
| `max_page_rows` | 10,000 | 10,000 | Largest requested page. |
| `max_subqueries` | 16 | 16 | Named queries in one request. |
| `max_filter_depth` | 16 | 16 | Nested filter contract. |
| `max_predicates` | 128 | 128 | Filter-node contract. |
| `max_in_values` | 10,000 | 10,000 | Set values and index seeks. |
| `max_aggregate_groups` | 10,000 | 10,000 | Aggregate groups per request, for projected relations and `groundhog.events`. |
| `default_timeout_ms` | 10,000 | 30,000 | Default Query execution timeout. |
| `max_timeout_ms` | 30,000 | 30,000 | Maximum requested `at_least` wait. |
| `memory_bytes_per_request` | 134,217,728 | 134,217,728 | Upper bound on loaded projected snapshot bytes. |
| `scan_bytes_per_request` | 1,073,741,824 | 1,073,741,824 | Second upper bound on loaded projected snapshot bytes. |
| `scan_rows_per_request` | 5,000,000 | 5,000,000 | Candidate rows examined by native execution. Event reads also have a fixed 10,000-ID limit. A `groundhog.events` aggregate must fit its whole input in the remaining budget. |
| `cpu_ms_per_request` | 20,000 | 20,000 | Upper bound on the Query execution timeout. |
| `delta_soft_rows` | 50,000 | 100,000 | Delta rows that start automatic compaction. |
| `delta_hard_rows` | 100,000 | 100,000 | Delta row ceiling applied by the compactor. |
| `delta_soft_segments` | 32 | 64 | Delta segments that start automatic compaction. |
| `delta_hard_segments` | 64 | 64 | Delta segment ceiling applied by the compactor. |

`executing_requests` cannot exceed `concurrent_requests`. Each default value cannot exceed its
matching maximum. The same ordering rule applies to soft and hard delta limits.

The HTTP and executor limits apply at request admission, parsing, consistency waiting, snapshot
loading, execution, response rendering, and cursor retention. For projected snapshots, the lower of
`memory_bytes_per_request` and `scan_bytes_per_request` is the loaded-byte limit. P0 measures the
bytes a request reads. It does not measure the memory a request retains, so both settings bound the
same measured quantity and the lower value applies. Set `memory_bytes_per_request` as an upper
bound on read bytes, not as a memory reservation.

This setting is also the effective ceiling on relation size. Groundhog charges every object it
reads against the limit before it adds those bytes, so a relation larger than the limit fails
during the load and returns HTTP 422 `query_limit_exceeded` rather than consuming an unbounded
amount of time and memory. The row count where that happens depends on the row width of the
relation. At the measured 942 bytes per row of the Agent Operations pack, the default of
134,217,728 bytes is reached near 136,000 rows. Raise both byte settings together to serve a larger
relation. Groundhog 0.3 cannot serve a relation that exceeds the effective loaded-byte limit.

Groundhog compacts
the projection delta when the delta rows reach `delta_soft_rows` or the delta segments reach
`delta_soft_segments`. The hard settings are a bound, not a preference. A projection that reaches
`delta_hard_rows` or `delta_hard_segments` must compact before Groundhog publishes its next epoch.
If that compaction fails, Groundhog keeps the previous Query snapshot visible and retries the same
epoch. Query continues to serve, and the growing lag appears in projection status. Event append,
replay, and follow do not use this path and continue during projection backpressure. See
[Query and Catalog](/groundhog/concepts/query) for the current relation, aggregate, and cursor
limits.

## Upgrade from 0.1

Do not copy Groundhog 0.1 warehouse settings into this section. Replace an old Query or warehouse
configuration with either `enabled = false` or the closed local Query configuration above.

Groundhog ignores the old warehouse files. Query uses `query.data_dir` for disposable indexed
state and continues to use the event log as its durable source.

## Path example

Given `/srv/acme/groundhog.toml`:

```toml
[data]
dir = "./state"

[server]
socket = "run/ground.sock"
```

the resolved paths are:

```text
/srv/acme/state
/srv/acme/run/ground.sock
```

These paths do not depend on the process working directory.

## Reload behavior

Groundhog loads configuration when a command starts.
`serve` does not reload the file while it runs.

Restart the service to apply token, socket, replay-limit, or Query changes.
Changing `data.dir` selects another deployment and does not move data.

## See also

[groundhog(1)](/groundhog/references/cli),
[`init`](/groundhog/commands#init),
[`serve`](/groundhog/commands#serve),
[deployment operations](/groundhog/operations/deployment)

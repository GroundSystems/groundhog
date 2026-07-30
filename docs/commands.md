---
title: groundhog commands
description: Complete command reference for the released groundhog binary.
---

The released binary supports this deployment lifecycle:

```text
init -> serve -> project -> verify
          |         |
        ingest    query/catalog

stop serve -> seal -> serve again
rebuild whenever the disposable warehouse must be replaced
```

Ingest, replay, query, and catalog use the HTTP API exposed by `serve`. They are not CLI
commands.

## Synopsis

```text
groundhog [--config <PATH>] <COMMAND>

groundhog init [DIR]
groundhog serve
groundhog seal
groundhog project
groundhog rebuild
groundhog verify [--chain]
```

Run `groundhog --help` or `groundhog <COMMAND> --help` for the help embedded in a particular
build.

## Behavior shared by all commands

### Configuration

`--config <PATH>` is global, may appear before or after the command, and defaults to
`./groundhog.toml`. Every command except `init` loads and validates it before opening
deployment state. Relative paths inside the file resolve against the file's directory.

`init` accepts the option because it is global but ignores it; initialization always writes
`<DIR>/groundhog.toml`.

Unknown configuration keys, missing files, and invalid limits are usage errors. The binary
supports security mode `open`. Commands that extend or attest history support anchor mode `none`;
they refuse stronger configured guarantees rather than silently weakening them.

See [Configuration](/references/configuration).

### Ownership and concurrency

| command | deployment access | can run with live `serve` |
|---|---|---:|
| `init` | creates or validates owned paths | no |
| `serve` | owns log writer and socket | it is the service |
| `seal` | owns log writer | no |
| `project` | reads log; publishes warehouse | yes |
| `rebuild` | reads log; replaces warehouse | yes |
| `verify` | read-only log analysis | yes |

The log has exactly one writer. `serve` and `seal` never bypass that lock. Warehouse publishers
coordinate separately and replace only complete generations.

### Output and exit status

Human lifecycle output and diagnostics go to standard error and are not stable parsing
interfaces. Lifecycle commands produce no machine-readable standard output. `verify` produces
one JSON document on standard output when it succeeds or conclusively finds a violation.

| code | meaning |
|---:|---|
| 0 | Command succeeded. |
| 1 | Operational failure such as I/O, permissions, engine failure, or a held lock. |
| 2 | Bad arguments or unusable configuration; deployment work was not attempted. |
| 3 | `verify` conclusively found a storage or integrity violation. |
| 4 | The binary deliberately refused an unsupported mode, anchor, capability, or format. |

## `init`

```text
groundhog init [DIR]
```

Creates an immediately serveable deployment. `DIR` defaults to the current directory.

Initialization creates an empty log, an empty query warehouse, and generated configuration:

```text
DIR/
├── groundhog.toml
└── data/
    ├── log/
    └── warehouse.duckdb
```

`groundhog.toml` is published last as the deployment commit point. An exact retry validates the
existing deployment and succeeds without rewriting it. A different configuration, a non-empty
log without committed configuration, a conflicting warehouse, unexpected entries in the owned
data directory, symlinks, or special files are refused rather than overwritten.

Standard output is empty. Standard error reports `initialized <DIR>` or
`already initialized <DIR>`.

```sh
groundhog init ./instance
```

## `serve`

```text
groundhog serve [--config <PATH>]
```

Acquires the log's single writer, opens the current published warehouse, and serves HTTP/1.1 over
the configured Unix domain socket. It never opens a TCP listener.

The current routes are:

| route | purpose |
|---|---|
| `POST /v1/events` | Atomic idempotent JSON batch ingest. |
| `GET /v1/events` | Ordered replay from a coherent log snapshot. |
| `POST /v1/query` | Confined read-only SQL against the published warehouse. |
| `GET /v1/catalog` | Published stream metadata and receipt. |

If `[server].token` is non-empty, every request requires `Authorization: Bearer <token>`.

The process prints `serving <socket-path>` immediately before entering socket binding and the
HTTP runtime. That line is not a readiness protocol; supervisors should wait for a successful
routed request. A live or unclassifiable existing socket is left untouched. Only a socket proven
stale is removed and rebound.

Replay sees committed log events immediately. Query and catalog see the last successful
`project` or `rebuild`. A running service adopts a newly published complete warehouse between
requests without restarting.

`SIGINT` or `SIGTERM` starts graceful shutdown. New work stops being admitted, queued mutations
reach their real storage outcome, and then writer ownership is released. If a client loses an
ingest response, it resolves the outcome by retrying identical content with the same batch ID.

```sh
groundhog serve --config ./instance/groundhog.toml
```

See [HTTP API](/references/http-api) and [Deployment operations](/operations/deployment).

## `seal`

```text
groundhog seal [--config <PATH>]
```

Rotates the append tail and seals every uncovered pending generation into immutable Parquet
segments. Sealing changes physical representation, not event values, IDs, order, batch
commitments, or chain head.

`seal` needs writer ownership, so stop `serve` first. It does not refresh the warehouse.

For each new segment, standard error reports:

```text
sealed <path> (<events> events, head <chain-head>)
```

An empty tail with nothing pending is exit 1 rather than a successful no-op.

```sh
groundhog seal --config ./instance/groundhog.toml
```

See [Storage](/concepts/storage).

## `project`

```text
groundhog project [--config <PATH>]
```

Captures one coherent log snapshot and publishes a complete warehouse generation containing
`events`, `meta.streams`, and `meta.projection_state`. Publication currently performs a full
recompute.

Publication is atomic, so failure never displaces the last good generation. The command reads the
log without owning its writer and may run while `serve` is active. Events appended after snapshot
capture wait for the next publication.

Standard output is empty. Standard error reports `projected <warehouse-path>`.

```sh
groundhog project --config ./instance/groundhog.toml
```

## `rebuild`

```text
groundhog rebuild [--config <PATH>]
```

Replays the complete captured log prefix into a replacement warehouse and publishes it atomically.
Use it to prove reconstructability or replace missing, stale, or invalid derived state.

`project` and `rebuild` currently both perform a full publication. Their intent differs: `project`
advances normal query freshness, while `rebuild` explicitly treats the warehouse as disposable.

`rebuild` may run while `serve` is active. Given the same log frontier and compatible build,
repeated rebuilds produce the same logical relations and receipt; byte-identical DuckDB files are
not promised.

Standard output is empty. Standard error reports `rebuilt <warehouse-path>`.

```sh
groundhog rebuild --config ./instance/groundhog.toml
```

## `verify`

```text
groundhog verify [--chain] [--config <PATH>]
```

Performs read-only analysis of one coherent log inventory. It never repairs or deletes files.

The default pass checks storage structure, segment file hashes and ranges, batch partitions and
digests, pending generations, tail framing, event order, and durable idempotency commitments.

`--chain` additionally recomputes every payload content hash, event hash, and the logical history
chain from genesis. It is more expensive because it reads and hashes all event content.

On exit 0 or exit 3, standard output contains exactly one JSON report:

```json
{
  "ok": true,
  "chain_checked": true,
  "segments_checked": 3,
  "pending_checked": 0,
  "events_checked": 1200,
  "orphans": [],
  "remnants": [],
  "failure": null
}
```

`orphans` are recognized non-authoritative files. `remnants` are excluded incomplete final state
that a compatible writer recovery may repair. Either list can be non-empty while verification
succeeds.

On exit 3, `failure` contains one stable code:

```text
manifest_invalid             segment_invalid
pending_invalid              tail_invalid
order_invalid                idempotency_invalid
file_hash_mismatch           batch_commitment_mismatch
content_hash_mismatch        event_hash_mismatch
chain_head_mismatch
```

Operational, usage, and refusal exits produce no JSON report. `verify --clean` is not available;
reported files are not permission for ad hoc deletion.

```sh
groundhog verify --chain --config ./instance/groundhog.toml
```

See [Verification and recovery](/operations/verification-and-recovery).

## Unavailable commands

The binary does not accept CLI `import`, `query`, `catalog`, `erase-payload`, `export-key`, or
`verify --clean`. Use the running HTTP API for ingest, replay, query, and catalog.

## See also

[Getting started](/guides/getting-started),
[CLI overview](/references/cli),
[Configuration](/references/configuration),
[HTTP API](/references/http-api)

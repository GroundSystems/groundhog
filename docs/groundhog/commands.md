---
title: groundhog commands
description: Complete command reference for the Groundhog 0.3 binary.
---

Groundhog 0.3 uses this deployment lifecycle:

```text
init -> serve -> ingest, replay, follow, streams, source retirement, optional Query
          |
       stop serve -> seal -> serve again

verify can run while serve is active
```

Ingest, replay, follow, stream enumeration, and source retirement use the HTTP API. Query,
Catalog, and projection status also have CLI clients that forward JSON over the configured Unix
socket.

## Synopsis

```text
groundhog [--config <PATH>] <COMMAND>

groundhog init [DIR]
groundhog init DIR --backend s3 --bucket <BUCKET> --region <REGION> --prefix <PREFIX>
groundhog serve
groundhog seal
groundhog verify [--chain]
groundhog query [FILE|-]
groundhog catalog [RELATION]
groundhog status PROJECTION
```

Run `groundhog --help` or `groundhog <COMMAND> --help` for the help in an installed build.

## Behavior shared by all commands

### Configuration

`--config <PATH>` is global and defaults to `./groundhog.toml`.
It can occur before or after the command.

Every command except `init` loads and validates the selected file before it opens deployment state.
Relative paths in the file resolve against the file's directory.

`init` accepts the global option but ignores it.
Initialization always writes `<DIR>/groundhog.toml`.

Unknown configuration keys and invalid limits are usage errors.
The binary serves only security mode `open`.
`serve`, `seal`, and `verify --chain` support only anchor mode `none`.
Plain `verify` checks storage without enforcing the configured anchor mode.

Groundhog 0.3 accepts a closed optional `[query]` section. Query is disabled by default and can run
only with the local event-log backend.
See [Configuration](/groundhog/references/configuration).

### Ownership and concurrency

| command | deployment access | can run with live `serve` |
|---|---|---:|
| `init` | creates or validates owned paths | an exact retry can |
| `serve` | owns the log writer and socket | it is the service |
| `seal` | owns the log writer | no |
| `verify` | reads one coherent log snapshot | yes |
| `query` | uses the configured Unix socket | yes |
| `catalog` | uses the configured Unix socket | yes |

The log has one writer.
`serve` and `seal` never bypass the writer lock.

### Output and exit status

Lifecycle output and diagnostics use standard error.
They are not stable parsing interfaces.

Lifecycle commands produce no machine-readable standard output.
`verify` produces one JSON document on standard output after a complete result.
`query` and `catalog` copy the HTTP response JSON to standard output without reformatting it.

| code | meaning |
|---:|---|
| 0 | The command succeeded. |
| 1 | An operational error occurred, such as I/O failure or a held lock. |
| 2 | The arguments or configuration were invalid. |
| 3 | `verify` found a storage or integrity violation. |
| 4 | The binary refused an unsupported mode, anchor, capability, or format. |

## `init`

```text
groundhog init [DIR]
```

`init` creates a deployment that `serve` can open immediately.
`DIR` defaults to the current directory.

Initialization creates this layout:

```text
DIR/
├── groundhog.toml
└── data/
    └── log/
```

`groundhog.toml` is the deployment commit point and is written last.
An exact retry validates the deployment and does not rewrite it.

The command refuses a non-empty log without committed configuration.
It preserves unrelated entries in `DIR`.
It refuses unrelated entries in `DIR/data`.
It also refuses unexpected symbolic links and special files in the deployment paths that it manages.
It permits known Groundhog 0.1 warehouse entries in `DIR/data` and leaves them unchanged.

Groundhog does not create a warehouse file.
It does not modify old warehouse files during an upgrade.

Standard error reports `initialized <DIR>` or `already initialized <DIR>`.

```sh
groundhog init ./instance
```

For S3 authoritative storage:

```sh
groundhog init /srv/ground/acme \
  --backend s3 \
  --bucket company-groundhog \
  --region us-west-2 \
  --prefix groundhog/production
```

S3 initialization lists the configured prefix. It creates `format.json`, the empty checkpoint, the
genesis commit, and `HEAD.json` in that order. It writes local `groundhog.toml` only after the remote
deployment is complete. An exact retry and reattachment to an authenticated advanced deployment
succeed without changing committed history.

## `serve`

```text
groundhog serve [--config <PATH>]
```

`serve` acquires the log writer and serves HTTP/1.1 over the configured Unix socket.
It opens only the durable log.
It never opens a TCP listener.

For S3, `serve` recovers and claims writer authority before it binds the Unix socket. Planned
shutdown drains admitted mutations, conditionally releases authority, and then exits. Serving does
not require `s3:ListBucket` or `s3:DeleteObject`.

The service always provides these routes:

| route | purpose |
|---|---|
| `POST /v1/events` | Append an atomic, idempotent JSON batch. |
| `GET /v1/events` | Replay events or follow new commits. |
| `GET /v1/streams` | Enumerate authoritative streams from the log. |
| `POST /v1/sources/retire` | Permanently retire one source. |

An enabled Query service adds `POST /v1/query`, `GET|HEAD /v1/catalog`,
`GET|HEAD /v1/catalog/relations/{relation}`, and
`GET|HEAD /v1/projections/{projection}/status`. Query requires `data.backend = "local"` and a
non-empty bearer token. Query exposes `groundhog.events` and the complete Agent Operations version 1
relation pack.

If `[server].token` is not empty, every request needs `Authorization: Bearer <token>`.

The process reports `serving <socket-path>` before it starts the HTTP runtime.
This message is not a readiness check.
Supervisors must wait for a successful routed request.

A live or unclassified existing socket remains untouched.
The process removes and replaces only a socket that it proves is stale.

`SIGINT` or `SIGTERM` starts a graceful shutdown.
The server stops new work and resolves queued mutations before it releases the writer.

If an ingest response is lost, retry identical content with the same batch ID.

```sh
groundhog serve --config ./instance/groundhog.toml
```

See [HTTP API](/groundhog/references/http-api) and [Deployment operations](/groundhog/operations/deployment).

## `query`

```text
groundhog query [FILE|-] [--config <PATH>]
```

`query` sends the input bytes to `POST /v1/query` over `[server].socket`. It reads a named file when
one is present. It reads standard input when the argument is omitted or is `-`.

The input must be no more than 1 MiB. The command does not rewrite or complete the JSON envelope.
The file or standard input must contain `v`, `consistency`, and exactly one of `query` or `queries`.

```sh
groundhog query ./event-query.json --config ./instance/groundhog.toml
groundhog query --config ./instance/groundhog.toml < ./event-query.json
```

The command adds `Content-Type: application/json` and the configured bearer token. It copies the
server JSON response to standard output without adding a newline. A 2xx status returns exit code 0.
A server error preserves its JSON body on standard output, reports the status on standard error,
and returns exit code 1.

See [Query and Catalog](/groundhog/concepts/query) for the request structure and current execution
limits.

## `catalog`

```text
groundhog catalog [RELATION] [--config <PATH>]
```

Without an argument, `catalog` sends `GET /v1/catalog`. A canonical relation name sends
`GET /v1/catalog/relations/{relation}`.

```sh
groundhog catalog --config ./instance/groundhog.toml
groundhog catalog groundhog.events --config ./instance/groundhog.toml
```

The output and HTTP error behavior match `query`. An invalid local relation name is a usage error
with exit code 2 and sends no request.

## `status`

```text
groundhog status PROJECTION [--config <PATH>]
```

`status` sends `GET /v1/projections/{projection}/status` for one canonical projection name.

```sh
groundhog status agent_operations --config ./instance/groundhog.toml
groundhog status groundhog_events --config ./instance/groundhog.toml
```

The output and HTTP error behavior match `query`. The command checks the projection name locally
before it sends the request. The name must start with a lowercase letter, contain only lowercase
letters, digits, and underscores, and use at most 63 bytes. Another name is a usage error with exit
code 2 and sends no request.

## `seal`

```text
groundhog seal [--config <PATH>]
```

`seal` rotates the append tail into immutable Parquet segments.
It does not change event values, IDs, order, batch commitments, or the chain head.

Stop `serve` before sealing because `seal` needs writer ownership.

For each new segment, standard error reports:

```text
sealed <path> (<events> events, head <chain-head>)
```

An empty tail with no pending work returns exit code 1.

```sh
groundhog seal --config ./instance/groundhog.toml
```

See [Storage](/groundhog/concepts/storage).

## `verify`

```text
groundhog verify [--chain] [--config <PATH>]
```

`verify` analyzes one coherent log inventory without changing files.

The default pass checks storage structure, segment hashes, event ranges, batches, pending
generations, tail framing, order, and idempotency commitments.

`--chain` also recomputes each content hash, event hash, and logical history-chain value.
This option reads and hashes all event content.

When local Query is enabled, `verify` also checks the exact `CURRENT` and `FALLBACK` references.
It checks each manifest, object size, object hash, row pack, index sidecar, receipt, and relation identity.
It also checks primary keys, row counts, and the Catalog metadata derived from the snapshot.
This Query pass is read-only and does not recover through `FALLBACK` when `CURRENT` is invalid.
An older `FALLBACK` registry gets reference, manifest, object, and receipt checks only.

Exit code 0 or 3 writes one JSON report to standard output:

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

An enabled Query configuration adds a `query` object. It reports the current snapshot, event frontier,
reference counters, object counters, relation counters, row counters, status, and typed failure.
Query-disabled and S3 reports keep the report shape shown above.

Verification recognizes `orphans` as non-authoritative files.
`remnants` are incomplete state that compatible recovery can exclude or repair.
Verification can succeed when either list is not empty.

Operational, usage, and refusal exits do not produce a JSON report.
`verify --clean` is not available.

```sh
groundhog verify --chain --config ./instance/groundhog.toml
```

See [Verification and recovery](/groundhog/operations/verification-and-recovery).

## Removed and unavailable commands

Groundhog 0.3 does not accept `project` or `rebuild`.
It does not provide a local SQL warehouse.

The binary also rejects CLI `import`, `erase-payload`, `export-key`, and `verify --clean`.
Use the HTTP API for ingest, replay, follow, stream enumeration, and source retirement.

## See also

[Getting started](/guides/getting-started),
[CLI overview](/groundhog/references/cli),
[Configuration](/groundhog/references/configuration),
[HTTP API](/groundhog/references/http-api)

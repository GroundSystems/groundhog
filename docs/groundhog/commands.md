---
title: groundhog commands
description: Complete command reference for the Groundhog 0.2 binary.
---

Groundhog 0.2 uses this deployment lifecycle:

```text
init -> serve -> ingest, replay, follow, streams, source retirement
          |
       stop serve -> seal -> serve again

verify can run while serve is active
```

Ingest, replay, follow, stream enumeration, and source retirement use the HTTP API.
They are not CLI commands.

## Synopsis

```text
groundhog [--config <PATH>] <COMMAND>

groundhog init [DIR]
groundhog serve
groundhog seal
groundhog verify [--chain]
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
The binary supports security mode `open` and anchor mode `none`.
It refuses configured guarantees that this release cannot provide.

Groundhog 0.2 rejects the removed `[query]` section with an exact migration instruction.
See [Configuration](/groundhog/references/configuration).

### Ownership and concurrency

| command | deployment access | can run with live `serve` |
|---|---|---:|
| `init` | creates or validates owned paths | no |
| `serve` | owns the log writer and socket | it is the service |
| `seal` | owns the log writer | no |
| `verify` | reads one coherent log snapshot | yes |

The log has one writer.
`serve` and `seal` never bypass the writer lock.

### Output and exit status

Lifecycle output and diagnostics use standard error.
They are not stable parsing interfaces.

Lifecycle commands produce no machine-readable standard output.
`verify` produces one JSON document on standard output after a complete result.

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
It also refuses unexpected entries, symbolic links, and special files in paths that it owns.

Groundhog does not create a warehouse file.
It does not modify old warehouse files during an upgrade.

Standard error reports `initialized <DIR>` or `already initialized <DIR>`.

```sh
groundhog init ./instance
```

## `serve`

```text
groundhog serve [--config <PATH>]
```

`serve` acquires the log writer and serves HTTP/1.1 over the configured Unix socket.
It opens only the durable log.
It never opens a TCP listener.

The service provides these routes:

| route | purpose |
|---|---|
| `POST /v1/events` | Append an atomic, idempotent JSON batch. |
| `GET /v1/events` | Replay events or follow new commits. |
| `GET /v1/streams` | Enumerate authoritative streams from the log. |
| `POST /v1/sources/retire` | Permanently retire one source. |

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

The default pass checks storage structure, segment hashes, event ranges, batches, pending generations, tail framing, order, and idempotency commitments.

`--chain` also recomputes each content hash, event hash, and logical history-chain value.
This option reads and hashes all event content.

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

Groundhog 0.2 does not accept `project` or `rebuild`.
It does not provide a local SQL warehouse.

The binary also rejects CLI `import`, `query`, `catalog`, `erase-payload`, `export-key`, and `verify --clean`.
Use the HTTP API for ingest, replay, follow, stream enumeration, and source retirement.

## See also

[Getting started](/guides/getting-started),
[CLI overview](/groundhog/references/cli),
[Configuration](/groundhog/references/configuration),
[HTTP API](/groundhog/references/http-api)

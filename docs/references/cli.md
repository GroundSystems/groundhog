---
title: groundhog(1)
description: CLI synopsis, global options, command index, streams, and exit status.
---

## Name

`groundhog`: maintain a Groundhog append-only event log and its embedded analytical warehouse.

## Synopsis

```text
groundhog [--config <PATH>] <COMMAND>
groundhog --help
groundhog --version
```

Current commands:

```text
groundhog init [DIR] [--config <PATH>]
groundhog serve [--config <PATH>]
groundhog seal [--config <PATH>]
groundhog project [--config <PATH>]
groundhog rebuild [--config <PATH>]
groundhog verify [--chain] [--config <PATH>]
```

## Description

`groundhog` is the Groundhog binary containing a durable event log, a rebuildable DuckDB
warehouse, a Unix-socket HTTP service, and operator lifecycle commands. Connectors and applications use the
HTTP interface; operators use the CLI to initialize, serve, publish, maintain, and verify one
deployment.

One deployment is selected by `groundhog.toml`. Its log is the durable truth. The warehouse is
derived state that may lag the log and can be replaced by replaying it.

The current binary runs locally in the operator's infrastructure. It enforces only security mode `open`.
Operations that would extend or attest history support integrity anchor `none`; they refuse a
stronger configured anchor requirement.

## Global options

### `--config <PATH>`

Selects the instance configuration. The default is `./groundhog.toml`.

The option is global and may appear before or after the subcommand. Every command except `init`
loads it. Relative paths inside the file resolve against the configuration file's directory.

`init` accepts the option because it is global, but ignores its value and writes
`<DIR>/groundhog.toml`.

### `-h`, `--help`

Print top-level or command-specific help and exit 0.

### `-V`, `--version`

Print the package version and exit 0. A release build may include a stamped source revision as
`<version>+<revision>`.

## Commands

| command | purpose |
|---|---|
| [`init [DIR]`](/commands#init) | Create or validate an immediately serveable deployment. |
| [`serve`](/commands#serve) | Run the ingest, replay, query, and catalog service. |
| [`seal`](/commands#seal) | Seal the append tail into immutable segments. |
| [`project`](/commands#project) | Publish a fresh warehouse generation. |
| [`rebuild`](/commands#rebuild) | Reconstruct the disposable warehouse from the log. |
| [`verify [--chain]`](/commands#verify) | Verify storage and optionally the integrity chain. |

The cohesive [commands reference](/commands) owns command behavior, concurrency, output,
exit status, and examples.

## Ownership and concurrency

| command | deployment access | may run while `serve` is active |
|---|---|---:|
| `init` | creates or validates owned paths | no |
| `serve` | log writer and public socket owner | it is the server |
| `seal` | log writer | no |
| `project` | coherent log reader; warehouse publisher | yes |
| `rebuild` | coherent log reader; warehouse publisher | yes |
| `verify` | coherent read-only log analysis | yes |

Only `serve` and `seal` mutate the log in the current CLI. They never bypass the one-writer rule.
`project` and `rebuild` coordinate with a separate warehouse-publication lock and publish complete
files atomically. A query already in progress remains pinned to its original generation.

## Standard streams

Human lifecycle output and diagnostics go to standard error. Its exact wording and line count are
not stable interfaces.

`init`, `serve`, `seal`, `project`, and `rebuild` have no machine-readable standard output.
`verify` writes exactly one JSON document to standard output on exit 0 or exit 3. Help and version
requests also use standard output.

Automation should use exit status, parse only documented standard-output documents, and treat
standard error as human context.

## Exit status

| code | class | meaning |
|---:|---|---|
| 0 | success | The command completed; every requested verification check passed. |
| 1 | operational | I/O, permission, engine, held-lock, batch-conflict, or corrupt-state open failure. |
| 2 | usage | Arguments or configuration are unusable; deployment work was not attempted. |
| 3 | verification | `verify` conclusively found a violation and emitted its JSON report. |
| 4 | refusal | The operation is deliberately unavailable for the security mode, anchor, capability, or compatible format. |

Configuration errors are usage failures because validation happens before deployment state is
opened. A malformed storage format found by `verify` is exit 3; a non-verification command that
cannot open corrupt state is operational exit 1. Exit 4 is for a structurally classifiable but
unsupported capability or compatibility state.

## Configuration

`groundhog.toml` controls the data directory, security mode, anchor requirement, Unix socket,
optional bearer token, query bounds, and replay bounds. Unknown keys are rejected.

See the [configuration reference](/references/configuration).

## Available HTTP surface

The current service exposes:

| route | function |
|---|---|
| `POST /v1/events` | Atomic idempotent JSON batch ingest. |
| `GET /v1/events` | Ordered replay from a coherent log snapshot. |
| `POST /v1/query` | Confined read-only SQL against one warehouse generation. |
| `GET /v1/catalog` | Published source/stream metadata and receipt. |

There are no current CLI wrappers for those client operations. See the
[HTTP API reference](/references/http-api).

## Unavailable names

The binary does not accept `import`, `query`, `catalog`, `erase-payload`, `export-key`, or
`verify --clean`. Passing one is a usage error. Unsupported commands are rejected rather than
partially performed.

## Examples

Initialize and serve a deployment:

```sh
groundhog init ./instance
groundhog serve --config ./instance/groundhog.toml
```

Publish a new warehouse generation while the service remains live:

```sh
groundhog project --config ./instance/groundhog.toml
```

Run deep verification:

```sh
groundhog verify --chain --config ./instance/groundhog.toml
```

## See also

[Getting started](/guides/getting-started),
[configuration](/references/configuration),
[events](/concepts/events),
[storage](/concepts/storage),
[warehouse](/concepts/warehouse),
[deployment operations](/operations/deployment)

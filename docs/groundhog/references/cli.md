---
title: groundhog(1)
description: Groundhog 0.2 CLI synopsis, options, commands, streams, and exit status.
---

## Name

`groundhog`: maintain and serve a durable append-only event log.

## Synopsis

```text
groundhog [--config <PATH>] <COMMAND>
groundhog init [DIR]
groundhog serve
groundhog seal
groundhog verify [--chain]
```

## Description

`groundhog` is one local binary with a durable event log and a Unix-socket HTTP service.
Connectors append source changes.
Applications replay events, follow new commits, enumerate streams, and build their own derived views.

One `groundhog.toml` file selects a deployment.
The event log is the durable record and uses storage schema version 1.

## Global option

`--config <PATH>` selects the configuration file.
The default is `./groundhog.toml`.

Every command except `init` loads this file.
`init` accepts the global option but writes `<DIR>/groundhog.toml` instead.

## Commands

| command | purpose |
|---|---|
| [`init`](/groundhog/commands#init) | Create or validate a deployment. |
| [`serve`](/groundhog/commands#serve) | Serve the log API over a Unix socket. |
| [`seal`](/groundhog/commands#seal) | Move the append tail into immutable Parquet segments. |
| [`verify`](/groundhog/commands#verify) | Check storage and optional chain integrity. |

Groundhog 0.2 removes `project` and `rebuild`.

## Ownership

| command | log access | can run with live `serve` |
|---|---|---:|
| `init` | creates or validates | no |
| `serve` | writer | it is the service |
| `seal` | writer | no |
| `verify` | coherent reader | yes |

Only one process can own the writer.

## Standard streams

Lifecycle output and diagnostics use standard error.
`verify` writes its machine-readable JSON report to standard output.

`init`, `serve`, and `seal` have no machine-readable standard output.
Help and version requests write to standard output and exit successfully.

## Exit status

| code | meaning |
|---:|---|
| 0 | Success. |
| 1 | Operational failure. |
| 2 | Invalid arguments or configuration. |
| 3 | A verified storage or integrity violation. |
| 4 | An unsupported mode, anchor, capability, or format. |

## Files

| path | purpose |
|---|---|
| `groundhog.toml` | Deployment configuration. |
| `[data].dir/log/` | Durable append-only event log. |
| `[server].socket` | Unix domain socket while `serve` runs. |

Groundhog 0.2 does not create or open `warehouse.duckdb`.
It ignores warehouse files left by Groundhog 0.1.

## Configuration

The configuration file sets the data directory, security mode, integrity anchor, server socket, bearer token, and replay limits.
Groundhog rejects unknown keys.

The removed `[query]` section produces this error:

```text
The [query] section is no longer supported. Remove it from groundhog.toml.
```

See [Configuration](/groundhog/references/configuration).

## HTTP service

`serve` provides four log API routes:

| method and path | purpose |
|---|---|
| `POST /v1/events` | Atomic, idempotent batch ingest. |
| `GET /v1/events` | Finite replay or continuous follow. |
| `GET /v1/streams` | Authoritative stream enumeration. |
| `POST /v1/sources/retire` | Permanent source retirement. |

The service does not provide `/v1/query` or `/v1/catalog`.

## Unsupported surface

The binary does not accept `project`, `rebuild`, `import`, `query`, `catalog`, `erase-payload`, `export-key`, or `verify --clean`.

It does not provide a TCP listener, local SQL, automatic derived views, payload erasure, key export, external anchors, or governed operation.

Use `groundhog --help`, `groundhog <COMMAND> --help`, and `groundhog --version` to inspect an installed build.

## Examples

```sh
groundhog init ./instance
groundhog serve --config ./instance/groundhog.toml
groundhog verify --chain --config ./instance/groundhog.toml
```

## See also

[Getting started](/guides/getting-started),
[configuration](/groundhog/references/configuration),
[events](/groundhog/concepts/events),
[storage](/groundhog/concepts/storage),
[deployment operations](/groundhog/operations/deployment)

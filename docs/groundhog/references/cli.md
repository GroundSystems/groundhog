---
title: groundhog(1)
description: Groundhog 0.3 CLI synopsis, options, commands, streams, and exit status.
---

## Name

`groundhog`: maintain and serve a durable append-only event log.

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

## Description

`groundhog` is one local binary with a durable event log and a Unix-socket HTTP service.
Connectors append source changes.
Applications replay events, follow new commits, enumerate streams, and build their own derived
views. A local deployment can also expose the built-in event relation through Query and Catalog.

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
| [`query`](/groundhog/commands#query) | Send one version 1 Query JSON request. |
| [`catalog`](/groundhog/commands#catalog) | List Catalog metadata or read one relation. |
| [`status`](/groundhog/commands#status) | Read one projection's publication and worker status. |

Groundhog 0.3 does not provide `project` or `rebuild`.

## Ownership

| command | log access | can run with live `serve` |
|---|---|---:|
| `init` | creates or validates | an exact retry can |
| `serve` | writer | it is the service |
| `seal` | writer | no |
| `verify` | coherent reader | yes |
| `query` | Unix-socket client | yes |
| `catalog` | Unix-socket client | yes |
| `status` | Unix-socket client | yes |

Only one process can own the writer.

## Standard streams

Lifecycle output and diagnostics use standard error.
`verify` writes its machine-readable JSON report to standard output.

`init`, `serve`, and `seal` have no machine-readable standard output.
`query`, `catalog`, and `status` copy the server JSON body to standard output without reformatting
it.
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
| `[data].dir/log/` | Durable local append-only event log. |
| `[data.s3]` bucket and prefix | Durable S3 object log. |
| `data/scratch/` | Disposable S3 codec and stream scratch files. |
| `[server].socket` | Unix domain socket while `serve` runs. |
| `[query].data_dir` | Disposable local Query snapshots and indexes. |

Groundhog 0.3 does not create or open `warehouse.duckdb`.
It ignores warehouse files left by Groundhog 0.1.

## Configuration

The configuration file selects the local or S3 backend and sets its location, security mode,
integrity anchor, server socket, bearer token, and replay limits.
Groundhog rejects unknown keys.

`serve`, `seal`, and `verify --chain` support only anchor mode `none`.
Plain `verify` checks storage without enforcing the configured anchor mode.

Query is disabled by default. An enabled Query section requires the local backend, a non-empty
server token, and a non-overlapping Query data directory:

```toml
[server]
token = "replace-with-a-secret"

[query]
enabled = true
backend = "local"
data_dir = "data/query"
```

See [Configuration](/groundhog/references/configuration).

## HTTP service

`serve` always provides four log API routes:

| method and path | purpose |
|---|---|
| `POST /v1/events` | Atomic, idempotent batch ingest. |
| `GET /v1/events` | Finite replay or continuous follow. |
| `GET /v1/streams` | Authoritative stream enumeration. |
| `POST /v1/sources/retire` | Permanent source retirement. |

When Query is enabled, `serve` also provides `POST /v1/query`, `GET|HEAD /v1/catalog`,
`GET|HEAD /v1/catalog/relations/{relation}`, and
`GET|HEAD /v1/projections/{projection}/status`.

## Unsupported surface

The binary does not accept `project`, `rebuild`, `import`, `erase-payload`, `export-key`, or
`verify --clean`.

It does not provide a TCP listener, SQL, operator-defined projection packs, payload erasure, key
export, external anchors, or governed operation.

Use `groundhog --help`, `groundhog <COMMAND> --help`, and `groundhog --version` to inspect an installed build.

## Examples

```sh
groundhog init ./instance
groundhog init ./remote --backend s3 --bucket company-groundhog --region us-west-2 --prefix groundhog/production
groundhog serve --config ./instance/groundhog.toml
groundhog verify --chain --config ./instance/groundhog.toml
groundhog catalog --config ./instance/groundhog.toml
groundhog query ./query.json --config ./instance/groundhog.toml
```

## See also

[Getting started](/guides/getting-started),
[configuration](/groundhog/references/configuration),
[events](/groundhog/concepts/events),
[storage](/groundhog/concepts/storage),
[deployment operations](/groundhog/operations/deployment)

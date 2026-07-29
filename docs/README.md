# Groundhog manual

This directory publishes the Groundhog manual in ordinary Markdown and a Unix-manual
structure:

- **commands** document executable entry points;
- **references** document stable configuration and API surfaces;
- **concepts** explain event data, durability, and query freshness from a user's perspective;
- **operations** cover deployment lifecycle, verification, and recovery; and
- **guides** provide end-to-end tasks.

## Start here

- [Getting started](guides/getting-started.md): complete the first local ingest, replay,
  publication, query, and verification loop.
- [groundhog(1)](references/cli.md): top-level CLI synopsis, options, commands, streams, and
  exit status.
- [Configuration](references/configuration.md): every accepted `groundhog.toml` field.
- [Operations](operations/deployment.md): run and maintain a deployment safely.

## Commands

All executable commands are documented together in [groundhog commands](commands.md), including
shared configuration, ownership, output, and exit behavior.

| command | purpose |
|---|---|
| [`init`](commands.md#init) | Create or validate a deployment. |
| [`serve`](commands.md#serve) | Run the Unix-socket HTTP service. |
| [`seal`](commands.md#seal) | Turn the append tail into immutable segments. |
| [`project`](commands.md#project) | Publish the current log frontier for SQL. |
| [`rebuild`](commands.md#rebuild) | Reconstruct the warehouse from the log. |
| [`verify`](commands.md#verify) | Verify storage and the integrity chain. |

## Published contract

The [contract](../spec/README.md) and
[compatibility vectors](../tests/test-vectors/README.md) are generated copies from the private
canonical [`GroundSystems/groundhog-src`](https://github.com/GroundSystems/groundhog-src)
repository. Do not edit these copies directly. The
[publication manifest](../spec/publication-manifest.json) lists every published file.

## System pages

| page | scope |
|---|---|
| [Events](concepts/events.md) | Event fields, kinds, identity, ordering, and batches. |
| [Storage](concepts/storage.md) | Durability, writer ownership, sealing, recovery, and backup. |
| [Warehouse](concepts/warehouse.md) | Publication, relations, receipts, catalog, and SQL. |
| [HTTP API](references/http-api.md) | Transport, authentication, routes, limits, and retries. |
| [Deployment](operations/deployment.md) | Ownership, freshness, maintenance order, and supervision. |
| [Verification and recovery](operations/verification-and-recovery.md) | Failure model, verification depth, and safe recovery. |

## Released surface

The binary accepts `init`, `serve`, `seal`, `project`, `rebuild`, and `verify [--chain]`.
Ingest, replay, query, and catalog are HTTP operations rather than CLI commands.

The binary does not currently provide CLI `import`, `query`, or `catalog`; `verify --clean`;
payload erasure; key export; a TCP listener; automatic projection; streaming ingest;
current-state relations; external anchors; or governed/locked operation. Unsupported names and
configuration are rejected rather than approximated.

Use `groundhog --help`, `groundhog <COMMAND> --help`, and `groundhog --version` to confirm
the surface of the installed binary.

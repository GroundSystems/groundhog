# Groundhog manual

This directory contains the Groundhog 0.2 manual in Markdown.

- **commands** document executable entry points
- **references** document configuration and HTTP surfaces
- **concepts** explain event data and durable storage
- **operations** cover deployment, verification, upgrade, and recovery
- **guides** provide complete tasks
- **SDKs** document supported client libraries

## Start here

- [Getting started](guides/getting-started.md) covers local ingest, replay, follow, streams, and verification.
- [groundhog(1)](references/cli.md) lists CLI options, commands, streams, and exit status.
- [Configuration](references/configuration.md) lists every accepted `groundhog.toml` field.
- [Deployment operations](operations/deployment.md) explains supervision, maintenance, backup, and upgrade.

## Product rule

Groundhog stores and serves the durable event log.
Applications build their own derived views from replay or follow.

Groundhog 0.2 does not include a warehouse, local SQL, query routes, catalog routes, or projection commands.

## Commands

The [groundhog commands](commands.md) page documents all commands.

| command | purpose |
|---|---|
| [`init`](commands.md#init) | Create or validate a deployment. |
| [`serve`](commands.md#serve) | Run the Unix-socket HTTP service. |
| [`seal`](commands.md#seal) | Move the append tail into immutable Parquet segments. |
| [`verify`](commands.md#verify) | Verify storage and optional chain integrity. |

## Published contract

The private source repository publishes the [contract](../spec/README.md) and [compatibility vectors](../tests/test-vectors/README.md).

The private canonical [`GroundSystems/groundhog-src`](https://github.com/GroundSystems/groundhog-src) repository publishes these files.
Do not edit the copies directly.

The [publication manifest](../spec/publication-manifest.json) lists every published file.

## System pages

| page | scope |
|---|---|
| [Events](concepts/events.md) | Event fields, identity, order, batches, preconditions, and source lifecycle. |
| [Storage](concepts/storage.md) | Durability, Parquet segments, writer ownership, recovery, and backup. |
| [HTTP API](references/http-api.md) | Ingest, replay, follow, streams, lifecycle, limits, and errors. |
| [Deployment](operations/deployment.md) | Supervision, consumers, maintenance, upgrade, and backup. |
| [Verification and recovery](operations/verification-and-recovery.md) | Verification depth and failure procedures. |
| [Python SDK](sdks/python.md) | Unix, HTTPS, ingest, replay, streams, and typed errors. |

## Released surface

The Groundhog 0.2 binary accepts `init`, `serve`, `seal`, and `verify [--chain]`.

The service provides atomic ingest, finite replay, follow, streams, and source retirement.
The Python SDK provides ingest, finite replay, and streams over Unix sockets or HTTPS.

The binary does not provide `project`, `rebuild`, local SQL, `/v1/query`, `/v1/catalog`, or a TCP listener.

Use `groundhog --help`, `groundhog <COMMAND> --help`, and `groundhog --version` to inspect an installed build.

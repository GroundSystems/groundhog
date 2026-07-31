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
- [Groundhog 0.2.0](releases/0.2.0.md) lists breaking changes and the upgrade procedure.
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

## Documentation ownership

This repository owns `docs.json`, navigation, branding, redirects, guides, and release notes.

Buildkite imports these generated paths:

| path | owner |
|---|---|
| `commands.md` | `GroundSystems/groundhog-src` |
| `concepts/` | `GroundSystems/groundhog-src` |
| `operations/` | `GroundSystems/groundhog-src` |
| `references/` | `GroundSystems/groundhog-src` |
| `sdks/` | `GroundSystems/groundhog-sdk-python` |

The root [`docs-sources.lock.json`](../docs-sources.lock.json) file records source commits and
published hashes. Edit generated pages in their owning repositories.

## Published interface

[`openapi.yaml`](../openapi.yaml) is the authoritative HTTP contract. The
[verification directory](../verify/README.md) contains the public conformance tools, black-box
checks, and compatibility fixtures.

`GroundSystems/groundhog-src` publishes the public contract and verification files separately.

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

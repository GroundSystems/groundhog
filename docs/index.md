---
title: Groundhog documentation
description: Install, use, and operate Groundhog with the released groundhog binary.
---

Groundhog keeps changes from connected systems as a durable, ordered event history and makes
that history available for replay and SQL analysis.

It runs as one local binary. Connectors submit events over HTTP; applications, agents,
automations, and operators replay or query them through the same API.

## Start here

- [Getting started](/guides/getting-started) walks through installation, ingest, replay,
  publication, query, and verification.
- [Commands](/commands) documents every command accepted by the binary.
- [HTTP API](/references/http-api) documents the client interface for ingest, replay, query,
  and catalog access.
- [Deployment operations](/operations/deployment) explains how to run and maintain an
  instance safely.

## How the manual is organized

- **Use Groundhog** covers the CLI and HTTP API.
- **Understand the system** explains events, durability, and query freshness from the outside.
- **Operate a deployment** covers configuration, supervision, verification, recovery, and
  backup.
- **Reference** provides concise Unix-manual-style summaries.

## Published contract

The public [Groundhog contract](https://github.com/GroundSystems/groundhog/tree/cleanup/spec)
and [compatibility vectors](https://github.com/GroundSystems/groundhog/tree/cleanup/tests/test-vectors)
are generated copies from the private canonical
[`GroundSystems/groundhog-src`](https://github.com/GroundSystems/groundhog-src) repository. Do
not edit the published copies directly.

Use `groundhog --help`, `groundhog <COMMAND> --help`, and `groundhog --version` to confirm
the installed binary's surface.

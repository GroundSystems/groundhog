---
title: Groundhog documentation
description: Install, use, and operate the Groundhog 0.2 durable event log.
---

Groundhog stores changes from connected systems as a durable, ordered event history.
It serves ingest, replay, follow, stream enumeration, and source lifecycle over a Unix socket.

Groundhog stores and serves the durable event log.
Applications build their own derived views from replay or follow.

Groundhog 0.2 does not include local SQL or a warehouse.

## Start here

- [Getting started](/guides/getting-started) covers installation, ingest, replay, follow, streams, and verification.
- [Commands](/commands) documents each command accepted by the binary.
- [HTTP API](/references/http-api) documents the log API, limits, errors, and retry behavior.
- [Deployment operations](/operations/deployment) explains supervision, maintenance, backup, and upgrade.
- [Python SDK](/sdks/python) documents the synchronous Unix and HTTPS client.

## Manual organization

- **Use Groundhog** covers the CLI and HTTP API.
- **Understand the system** explains events and durable storage.
- **Operate a deployment** covers configuration, supervision, verification, recovery, backup, and upgrade.
- **Reference** provides concise CLI and SDK details.

## Published contract

The private canonical source repository publishes the public
[Groundhog contract](https://github.com/GroundSystems/groundhog/tree/cleanup/spec) and
[compatibility vectors](https://github.com/GroundSystems/groundhog/tree/cleanup/tests/test-vectors).

Do not edit the public copies directly.

Use `groundhog --help`, `groundhog <COMMAND> --help`, and `groundhog --version` to inspect the installed binary.

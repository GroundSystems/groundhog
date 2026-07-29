---
title: Deployment operations
description: Deploy, supervise, publish, maintain, and back up one Groundhog instance.
---

## Name

`groundhog-operations`: deploy, supervise, publish, maintain, and back up one instance.

## Instance boundary

One service instance owns one configured data directory. Exactly one process owns its log writer;
clients communicate over the configured Unix socket.

The same deployment may be supervised by an SDK/application or by launchd, systemd, or another
operator process manager. Both use the same binary, configuration, socket, writer lock, recovery
path, and HTTP contract.

Groundhog is passive toward source systems. Connectors, schedulers, agents, and action
executors run outside it and retain their own credentials and cursors.

## First deployment

1. Initialize an empty directory:

   ```sh
   groundhog init /srv/ground/acme
   ```

2. Review `/srv/ground/acme/groundhog.toml`, its token, and filesystem permissions.

3. Start the service:

   ```sh
   groundhog serve --config /srv/ground/acme/groundhog.toml
   ```

4. Wait for a successful routed request, not merely a lifecycle log line:

   ```sh
   curl --unix-socket /srv/ground/acme/data/ground.sock http://ground/v1/catalog
   ```

5. Configure connectors to submit stable idempotent batches to `POST /v1/events`.

## Supervision

Run `serve` as a foreground process. Let the supervisor own restart policy and capture standard
error. Send `SIGTERM` for planned shutdown and allow the process to exit before starting a
writer-owning maintenance command.

A supervisor should consider the instance ready only after a real authenticated routed request
succeeds. Socket-path existence or the `serving ...` diagnostic alone is insufficient.

If a bearer token is configured, health probes must include it. `GET /v1/catalog` verifies
routing plus the currently published warehouse. A replay request can additionally exercise log
reads when desired.

## Command concurrency

| operation | log writer required | safe with live `serve` | changes warehouse |
|---|---:|---:|---:|
| ingest over HTTP | through server | yes | no |
| replay over HTTP | no | yes | no |
| `seal` | yes | no | no |
| `project` | no | yes | atomically replaces |
| `rebuild` | no | yes | atomically replaces |
| `verify` | no | yes | no |

Never try to work around a held writer by deleting `data/log/.lock`. Stop the owning process and
wait for it to release the data directory.

## Publication policy

The binary does not publish the warehouse automatically. Choose when query/catalog freshness
should advance and
run:

```sh
groundhog project --config /srv/ground/acme/groundhog.toml
```

The service may remain live. Publication captures one coherent frontier. Appends after snapshot
capture appear in the next publication. Receipts identify the current warehouse frontier.

Possible operator policies include:

- after a known connector sync completes;
- before a scheduled reporting or agent-analysis window;
- from an external periodic scheduler; or
- on demand when catalog/query freshness is required.

Do not infer SQL freshness from service uptime. Compare the response receipt's
`as_of_event_id` with replay/log progress appropriate to the application.

## Sealing policy

Sealing is manual and does not run on configured age/size thresholds. A planned
maintenance window is:

1. stop `serve` with `SIGTERM` and wait for exit;
2. run `groundhog seal`;
3. optionally run `groundhog verify --chain`; and
4. restart `serve` and probe a routed endpoint.

An empty tail makes `seal` exit 1. Treat that as “nothing to seal” only when the operator has
independently established that no pending work is expected; the CLI intentionally does not turn
it into success.

Sealing has no effect on query freshness and does not require a subsequent rebuild for logical
correctness.

## Rebuilds

Run `rebuild` to replace derived state or prove it can be reconstructed:

```sh
groundhog rebuild --config /srv/ground/acme/groundhog.toml
```

It may run while serving. Subsequent query/catalog requests adopt the new complete generation.
For an operational proof, retain the pre/post receipts and compare logical query results, not
DuckDB file bytes.

## Verification cadence

Structural verification is cheaper and useful for frequent checks:

```sh
groundhog verify --config /srv/ground/acme/groundhog.toml
```

Deep chain verification reads and hashes all content and is appropriate for scheduled integrity
checks, release/upgrade gates, backup validation, and restore drills:

```sh
groundhog verify --chain --config /srv/ground/acme/groundhog.toml
```

Capture the JSON report from standard output separately from standard-error diagnostics.

## Monitoring

Monitor:

- process exit and restart loops;
- routed API availability over the socket;
- HTTP 429 overload and `Retry-After` behavior;
- HTTP 503 writer-poisoned responses, which require reopen;
- ingest 409 conflicts, which indicate batch-ID misuse;
- query/catalog receipt age relative to the application's freshness requirement;
- verification exit status and failure code; and
- filesystem capacity for the durable log and warehouse publication.

Human standard-error text may change. Use exit codes, HTTP status, response structures, and
receipts as stable automation inputs.

## Backups

The log is the backup-critical artifact; the warehouse is rebuildable. The binary does not include a
backup command or online-copy protocol.

Coordinate a filesystem snapshot/copy so it captures a coherent log state. A conservative manual
procedure stops the writer, copies configuration plus `data/log/`, restarts service, and validates
the copy in an isolated restore drill. Do not point two writers at the same copied directory.

A useful restore drill:

1. restore to an isolated path;
2. adjust only deployment-specific paths in the restored configuration if necessary;
3. run structural and chain verification;
4. run `rebuild` to construct a fresh warehouse; and
5. serve on an isolated socket and compare receipts and known queries.

## Upgrades

Before replacing a binary:

- retain the previous pinned binary and a coherent backup;
- inspect release notes for storage reader/writer floors;
- run `verify --chain` with the current build;
- stop the writer cleanly; and
- start the new build against one deployment at a time and probe public routes.

A binary that cannot interpret or mutate a data directory refuses it. Do not bypass compatibility
checks or edit storage metadata.

## Security posture

The binary runs locally in the operator's infrastructure. Protect the configuration, socket parent, data directory,
backups, process account, and any operator-managed proxy. A bearer token protects API requests
but does not encrypt owner-readable files or provide governed/locked operation.

Do not expose the socket through a remote front door without adding transport security, access
control, and operational limits appropriate to that boundary.

## See also

[groundhog(1)](/references/cli),
[configuration](/references/configuration),
[verification and recovery](/operations/verification-and-recovery),
[storage](/concepts/storage)

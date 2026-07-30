---
title: Deployment operations
description: Deploy, supervise, maintain, upgrade, and back up one Groundhog 0.2 instance.
---

## Name

`groundhog-operations`: operate one durable event-log instance.

## Instance boundary

One service instance owns one configured data directory.
One process owns its log writer.
Clients communicate over the configured Unix socket.

An SDK, application, launchd, systemd, or another process manager can supervise the deployment.
Each option uses the same binary, configuration, socket, writer lock, recovery path, and HTTP contract.

Groundhog does not contact source systems.
Connectors and schedulers run outside it and keep their own credentials and source cursors.

Derived-view consumers also run outside Groundhog.
They use replay or follow to update their own databases and analytical systems.

## First deployment

1. Initialize an empty directory.

   ```sh
   groundhog init /srv/ground/acme
   ```

2. Review `/srv/ground/acme/groundhog.toml`, its token, and filesystem permissions.

3. Start the service.

   ```sh
   groundhog serve --config /srv/ground/acme/groundhog.toml
   ```

4. Wait for a successful routed request.

   ```sh
   curl --unix-socket /srv/ground/acme/data/ground.sock http://ground/v1/streams
   ```

5. Configure connectors to submit stable idempotent batches to `POST /v1/events`.

6. Configure consumers to replay or follow events and save durable cursors.

## Supervision

Run `serve` as a foreground process.
Let the supervisor own restart policy and standard-error capture.

Send `SIGTERM` for planned shutdown.
Wait for exit before you start a command that needs the writer.

A socket path or `serving ...` message does not prove readiness.
Use a routed authenticated request.

`GET /v1/streams?limit=1` checks routing and a coherent log read.
Use a narrow finite replay when a probe must check a known event.

## Command concurrency

| operation | log writer required | safe with live `serve` |
|---|---:|---:|
| ingest over HTTP | through the server | yes |
| finite replay over HTTP | no | yes |
| follow over HTTP | no | yes |
| stream enumeration over HTTP | no | yes |
| source retirement over HTTP | through the server | yes |
| `seal` | yes | no |
| `verify` | no | yes |

Do not delete `data/log/.lock` to bypass a held writer.
Stop the owning process and wait for it to release the data directory.

## Consumer policy

Groundhog stores and serves the durable event log.
Applications build derived views from replay or follow.

A consumer must save its last applied event ID.
Use one transaction for the derived-view update and cursor update when the target system supports it.

Reconnect follow with the exclusive `after` cursor after shutdown or transport failure.
Use finite replay to fill gaps before another follow session.

Consumers must define their own rebuild procedure.
That procedure starts from an empty derived view and replays the Groundhog log.

## Sealing policy

Sealing is manual.
Groundhog does not seal on configured age or size thresholds.

Use this maintenance sequence:

1. Stop `serve` with `SIGTERM` and wait for exit.
2. Run `groundhog seal`.
3. Run `groundhog verify --chain` when the maintenance policy requires it.
4. Restart `serve`.
5. Probe a routed endpoint.

An empty tail makes `seal` return exit code 1.
Treat this result as no work only when the operator expects no pending events.

Sealing creates immutable Parquet log segments.
It does not change the logical event history.

## Verification cadence

Structural verification supports frequent checks:

```sh
groundhog verify --config /srv/ground/acme/groundhog.toml
```

Deep verification reads and hashes all content:

```sh
groundhog verify --chain --config /srv/ground/acme/groundhog.toml
```

Use deep verification for release gates, upgrade gates, backup validation, and restore drills.
Store the JSON report from standard output separately from diagnostics.

## Monitoring

Monitor these signals:

- process exits and restart loops
- routed API availability over the socket
- HTTP 429 responses and `Retry-After` behavior
- HTTP 503 responses that require a new serving session
- ingest 409 conflicts caused by batch ID or stream frontier misuse
- follow terminal reasons and reconnect progress
- consumer cursor age and derived-view processing delay
- verification exit status and failure code
- filesystem capacity for `data/log/`.

Do not parse standard-error text for automation.
Use exit codes, HTTP status, stable error codes, and typed response fields.

## Backups

The durable log is the backup-critical artifact.
Groundhog does not include a backup command or online-copy protocol.

A conservative manual procedure is:

1. Stop the writer.
2. Copy `groundhog.toml` and `data/log/`.
3. Restart the service.
4. Restore the copy to an isolated path.
5. Run structural and chain verification.
6. Serve the restore on an isolated socket.
7. Compare known replay events, stream summaries, and receipts.

Do not point two writers at the same original or copied directory.

## Upgrade from 0.1

Before you replace the binary:

1. Keep the previous pinned binary and a coherent backup.
2. Read the 0.2 release notes.
3. Run `verify --chain` with the 0.1 build.
4. Stop the writer cleanly.
5. Remove the `[query]` section from `groundhog.toml`.
6. Start Groundhog 0.2 against one deployment.
7. Probe `GET /v1/streams` and a known replay request.
8. Run `verify --chain` with Groundhog 0.2.
9. Confirm that application consumers can rebuild or continue their derived views.

Groundhog 0.2 ignores these old files:

```text
data/warehouse.duckdb
data/warehouse.duckdb.publish.lock
data/.warehouse.duckdb.candidate-*
```

The runtime does not open or delete them.
Keep them during the first upgrade checks for a reversible deployment change.

Delete them manually only after the new binary, log verification, backup, and consumers pass their checks.

A binary that cannot interpret a data directory refuses it.
Do not bypass compatibility checks or edit storage metadata.

## Security posture

Groundhog runs in the operator's infrastructure.
Protect the configuration, socket parent, data directory, backups, and process account.

A bearer token protects API requests.
It does not encrypt owner-readable files or provide governed operation.

Do not expose the socket through a remote service without suitable transport security, access control, and operational limits.

## See also

[groundhog(1)](/references/cli),
[configuration](/references/configuration),
[verification and recovery](/operations/verification-and-recovery),
[storage](/concepts/storage)

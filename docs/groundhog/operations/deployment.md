---
title: Deployment operations
description: Deploy, supervise, maintain, upgrade, and back up one Groundhog 0.3 instance.
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

External derived-view consumers use replay or follow to update their own databases and analytical
systems. An enabled local Query service separately exposes Groundhog-owned immutable indexed state.

## First deployment

1. Initialize an empty directory.

   ```sh
   groundhog init /srv/ground/acme
   ```

2. Review `/srv/ground/acme/groundhog.toml`, its optional token, and filesystem permissions.

3. Start the service.

   ```sh
   groundhog serve --config /srv/ground/acme/groundhog.toml
   ```

4. Wait for a successful routed request.

   ```sh
   curl --unix-socket /srv/ground/acme/data/ground.sock \
     -H 'Authorization: Bearer <token>' \
     http://ground/v1/streams
   ```

   Omit the `Authorization` header when the configuration contains an empty token.

5. Configure connectors to submit stable idempotent batches to `POST /v1/events`.

6. Configure consumers to replay or follow events and save durable cursors.

7. If the deployment needs Query, stop the service, configure the closed `[query]` section with a
   non-empty token, and restart it. Query is available only with the local event-log backend.

For an S3 deployment, replace step 1 with:

```sh
groundhog init /srv/ground/acme \
  --backend s3 \
  --bucket company-groundhog \
  --region us-west-2 \
  --prefix groundhog/production
```

Supply credentials through the standard AWS credential provider chain. Do not store AWS credentials
in `groundhog.toml`. See [S3 operations](/groundhog/operations/s3).

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
| Query or Catalog over HTTP | Query snapshot reader | yes |
| `groundhog query` or `groundhog catalog` | Unix-socket client | yes |
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

Groundhog rebuilds the built-in event index from the durable log when Query state is missing or
invalid at startup. It catches the index and the projections up during startup. A bounded
publication worker follows new durable events while `serve` runs and publishes new Query snapshots.
Restart `serve` only when the worker stops or projection status reports a failure.

## Sealing policy

Sealing is manual.
Groundhog does not seal on configured age or size thresholds.

Use this maintenance sequence:

1. Stop `serve` with `SIGTERM` and wait for exit.
2. Run `groundhog seal --config /srv/ground/acme/groundhog.toml`.
3. Run the deep verification command when the policy requires it.

   ```sh
   groundhog verify --chain --config /srv/ground/acme/groundhog.toml
   ```

4. Restart `serve`.
5. Probe a routed endpoint.

An empty tail with no uncovered pending generation makes `seal` return exit code 1.
Treat this result as no work only when the operator expects no unsealed events.

Sealing creates immutable Parquet log segments.
It does not change the logical event history.

For S3, use the complete [planned seal outage](/groundhog/operations/s3#planned-seal-outage)
procedure. Run it before 1,024 active chunks or 256 MiB of stored active chunk bytes. A normal S3
seal refuses a live writer and never deletes the replaced chunk objects.

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
- Query snapshot frontier, `query_unavailable`, and `projection_frontier_timeout`
- `/v1/projections/agent_operations/status`, including event lag and failure details
- the compaction phase, failed run count, and last failure in the same status response
- Query limit and overload responses
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

`query.data_dir` contains derived local indexes and snapshots. It is not required to reconstruct the
built-in event relation. A backup can include it to reduce rebuild work, but the restore must still
validate it against the durable event log.

For S3, the configured remote prefix is authoritative. Loss of the local directory is not loss of an
acknowledged mutation. Reattach with the exact bucket, region, and prefix. Use AWS account controls,
versioning or replication policy, and backup policy outside Groundhog. Do not grant the Groundhog
process delete permission.

## Upgrade from 0.1

Before you replace the binary:

1. Keep the previous pinned binary and a coherent backup.
2. Read the 0.3 release notes.
3. Run `verify --chain` with the 0.1 build.
4. Stop the writer cleanly.
5. Replace old warehouse or Query settings with the Groundhog 0.3 closed `[query]` section. Leave
   it disabled for the first start unless Query is required.
6. Start Groundhog 0.3 against one deployment.
7. Probe `GET /v1/streams` and a known replay request.
8. If Query is enabled, probe authenticated `GET /v1/catalog` and one bounded event query.
9. Run `verify --chain` with Groundhog 0.3.
10. Confirm that application consumers can rebuild or continue their derived views.

Groundhog 0.3 ignores these old files:

```text
data/warehouse.duckdb
data/warehouse.duckdb.wal
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

A configured bearer token protects API requests.
An empty token disables HTTP authentication.
The token does not encrypt owner-readable files or provide governed operation.

Query cannot start with an empty bearer token. This requirement does not encrypt the Unix socket or
configuration file.

Do not expose the socket through a remote service without suitable transport security, access
control, and operational limits.

## See also

[groundhog(1)](/groundhog/references/cli),
[configuration](/groundhog/references/configuration),
[verification and recovery](/groundhog/operations/verification-and-recovery),
[storage](/groundhog/concepts/storage)

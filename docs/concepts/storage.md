---
title: Storage and durability
description: Understand durability, writer ownership, sealing, recovery, and backup.
---

Users interact with Groundhog through the CLI and HTTP API. Files under the configured data
directory belong to Groundhog and should not be edited directly.

## Durable history and query data

The data directory contains two kinds of state:

- the event log is the durable history and the backup-critical artifact;
- the warehouse is query data derived from that history.

The warehouse can be recreated with `rebuild`. A backup that contains only the warehouse is not
a backup of event history.

## What a successful ingest means

An ingest response with `status: "committed"` or `status: "duplicate"` means the complete batch
is durable.

If the connection closes or times out before a response arrives, the result is unknown. Retry the
same content with the same `(source, batch_id)`. The server returns the original receipt if the
batch was already committed or commits it once if it was not.

HTTP 503 on ingest means the service cannot safely accept more writes. Restart it, allow the data
directory to reopen, and then retry any ambiguous batch identically.

## One writer per data directory

Only one process may write a data directory at a time.

- `serve` owns it while the service is running;
- `seal` needs exclusive writer access;
- `project`, `rebuild`, and `verify` may run while `serve` is active.

If a command reports that the writer is held, stop the owning process and wait for it to exit. Do
not delete files in the data directory to force access.

## Sealing

`seal` consolidates committed history into read-optimized immutable storage. It does not change
event values, IDs, order, batch identities, or integrity commitments.

Stop `serve` before sealing. Sealing does not refresh SQL or the catalog; run `project` separately
when query freshness should advance.

## Coherent reads

Replay, project, rebuild, and verify each use one coherent history frontier. Concurrent ingest
cannot make one operation mix different points in history.

A captured frontier may be behind a later append. Replay cursors and warehouse receipts identify
the frontier used by a response.

## Restart and recovery

After a crash or unclean stop:

1. confirm the previous process has exited;
2. start `serve` with the same configuration;
3. wait for a successful routed request;
4. retry ambiguous batches with the same IDs and content; and
5. run `verify` if the interruption requires an integrity check.

The binary refuses a data directory when it cannot identify one safe history. Do not edit stored
files in an attempt to force recovery; preserve a copy and restore from a verified backup when
necessary.

## Backup and restore

The binary does not provide an online backup command. A conservative backup procedure is:

1. stop `serve` cleanly;
2. copy `groundhog.toml` and the durable log;
3. restart the service; and
4. periodically validate a restored copy.

Validate a restore in an isolated directory:

```sh
groundhog verify --chain --config ./restored/groundhog.toml
groundhog rebuild --config ./restored/groundhog.toml
```

Then serve the restored instance on an isolated socket and compare expected receipts and query
results.

## See also

[`seal`](/commands#seal),
[`verify`](/commands#verify),
[Deployment operations](/operations/deployment)

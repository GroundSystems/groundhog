---
title: Storage and durability
description: Understand log durability, Parquet segments, writer ownership, recovery, and backup.
---

Users interact with Groundhog through the CLI and HTTP API.
Do not edit files under the configured data directory.

## Durable event log

Groundhog 0.2 stores one kind of product state: the durable append-only event log.
The log is the backup-critical artifact.

Groundhog stores the log under `[data].dir/log/`.
The durable storage schema remains version 1.

Groundhog stores active appends in a framed tail.
The `seal` command moves committed history into immutable Parquet segments.

Parquet is the log-segment format.
Groundhog does not need DuckDB to read, verify, or seal these segments.

The log directory contains these required entries:

```text
log/
├── manifest.jsonl
├── tail.ndjson
├── pending/
└── segments/
```

The logical log contains active segments, uncovered pending generations, and the committed tail
prefix. Event IDs increase across the complete sequence. Ranges cannot overlap.

## Format and commit records

The first manifest record identifies format `groundhog/log` and storage schema version 1. Each
manifest body uses RFC 8785 canonical JSON. One LF byte commits the body after the body reaches
durable storage.

The tail contains one canonical JSON event per line. Each line also has `batch_len` and
`batch_digest` framing fields. One fsync after all batch lines is the batch commit point.

Recovery accepts only complete batches with valid framing, hashes, digests, and event order. A
writer can remove an incomplete final batch. Groundhog treats malformed committed content as
corruption.

## Pending generations and segments

Rotation renames a nonempty tail to
`pending/<first_event_id>_<last_event_id>.ndjson`. The pending generation remains authoritative
until one committed manifest record covers its exact range.

Sealing writes one immutable Parquet segment to
`segments/<first_event_id>_<last_event_id>_<sha256>.parquet`. The file hash, manifest range, row
count, event order, and batch partition must agree.

Each segment uses Zstandard compression and stores event columns in this order: `event_id`,
`source`, `stream`, `record_key`, `kind`, `occurred_at`, `observed_at`, `payload`,
`content_hash`, `batch_id`, and `event_hash`.
Groundhog can select valid Parquet encodings without reproducing identical segment bytes.

The manifest LF commit makes the segment authoritative. Before that commit, the pending generation
remains authoritative.

## Integrity chain

The chain starts with SHA-256 of the ASCII bytes `groundhog/genesis/v1`. Each later head hashes the
previous raw 32-byte head followed by the event hash as raw 32-byte data.

Each segment record stores the chain head at its last event. Chain verification recomputes payload
hashes, event hashes, lifecycle state, and all chain heads.

## What a successful ingest means

An ingest response with `status: "committed"` or `status: "duplicate"` means the complete batch is durable.

A lost connection or timeout leaves the client without a known result.
Retry the same content with the same `(source, batch_id)`.

The server returns the original receipt if the batch already committed.
Otherwise, it commits the batch once.

HTTP 503 means the active writer cannot safely accept more mutations.
Restart the service and let Groundhog reopen the log before a retry.

## One writer per data directory

Only one process can write a data directory at a time.

- `serve` owns the writer while the service runs.
- `seal` needs exclusive writer access.
- `verify` can read while `serve` runs.

If a command reports a held writer, stop the owning process and wait for exit.
Do not delete lock files to force access.

## Sealing

`seal` consolidates committed history into immutable Parquet segments.
It does not change event values, IDs, order, batch identities, or integrity commitments.

Stop `serve` before sealing.
Restart the service after the command finishes.

## Coherent reads

Each replay, stream enumeration, and verification operation uses one coherent history snapshot.
Concurrent ingest cannot mix different frontiers in one finite response.

Finite replay identifies its captured frontier with `snapshot_through_event_id`.
Stream enumeration uses the same field and supports an anchored `through` parameter for later pages.

Follow starts with one coherent snapshot and then reads later committed events in order.

## Restart and recovery

After a crash or unclean stop:

1. Confirm that the previous process has exited.
2. Start `serve` with the same configuration.
3. Wait for a successful routed request.
4. Retry ambiguous batches with the same IDs and content.
5. Run `verify` when the interruption needs an integrity check.

The binary refuses a data directory when it cannot identify one safe history.
Do not edit stored files to force recovery.

A read-only open does not repair storage. A writer applies recognized repairs under the exclusive
writer lock and fsyncs each repair. An uncertain write, fsync, rename, or truncate closes that
writer session until Groundhog reopens the log.

Preserve a copy and restore from a verified backup when Groundhog refuses the only history.

## Old warehouse files

Groundhog 0.2 ignores these Groundhog 0.1 files:

```text
data/warehouse.duckdb
data/warehouse.duckdb.wal
data/warehouse.duckdb.publish.lock
data/.warehouse.duckdb.candidate-*
```

Groundhog never deletes them automatically.
They are not part of the event log and are not needed after the upgrade.

Operators can delete them manually after they verify the 0.2 deployment and backup.

## Backup and restore

Groundhog does not provide an online backup command.
A conservative backup procedure is:

1. Stop `serve` cleanly.
2. Copy `groundhog.toml` and `data/log/`.
3. Restart the service.
4. Validate a restored copy at regular intervals.

Validate the restore in an isolated directory:

```sh
groundhog verify --config ./restored/groundhog.toml
groundhog verify --chain --config ./restored/groundhog.toml
```

Then serve the restore on an isolated socket.
Compare known replay events, stream summaries, and ingest receipts.

## See also

[`seal`](/groundhog/commands#seal),
[`verify`](/groundhog/commands#verify),
[Deployment operations](/groundhog/operations/deployment)

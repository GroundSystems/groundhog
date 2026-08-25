---
title: Verification and recovery
description: Verify a deployment and respond to startup, storage, and integrity failures.
---

## Name

`groundhog-recovery`: verification depth, crash recovery, and operator response.

## Principles

Groundhog opens a data directory only when it can identify one authoritative durable history.
It refuses ambiguous or contradictory state.

Read-only commands do not repair data.
A writer open can finish recognized interrupted writes before it accepts new mutations.

Verification is always read-only.

For S3, ordinary recovery and verification use exact object keys. They do not list the bucket or
remote prefix. Preserve the exact bucket and prefix during investigation.

## Ordinary open analysis

Every open checks these stored facts:

- a compatible storage format
- one coherent committed history frontier
- strictly ordered event ranges
- consistent durable `(source, batch_id)` commitments.
- consistent source-retirement commitments.

A writer can exclude or finish a recognized interrupted final write.
Groundhog does not discard conflicting complete records or representations.

## Structural verification

`groundhog verify` checks stored history:

- the SHA-256 digest of each authoritative segment
- the Parquet row count and exact event-ID range
- strict row order in each segment
- exact segment partitioning by recorded batch
- batch digests recomputed from event commitments
- matching pending and tail facts in the captured inventory.

The report also lists recognized orphans and repairable remnants without changing them.

## Chain verification

`groundhog verify --chain` also recomputes these values for each event:

1. `content_hash` from canonical payload JSON.
2. `event_hash` from the canonical fixed envelope.
3. The ordered logical chain from the fixed genesis head.
4. Source-retirement and successor-lineage state from ordered events.

It compares chain heads at segment boundaries and the captured frontier.
It detects changes that conflict with the available commitments and recorded chain heads.

Local chain consistency does not prove that an owner did not replace the complete directory coherently.
Groundhog 0.3 does not support external anchors.

## Query verification

An enabled local Query configuration adds a deep Query pass after log verification succeeds.
The pass reads the exact `CURRENT` and `FALLBACK` references without applying recovery selection.

The pass checks these facts:

- each reference names a canonical content-addressed manifest
- each manifest object has the declared size and SHA-256 digest
- each base and delta row pack has canonical structure and typed rows
- each relation has the complete declared index sidecar set
- each base and delta receipt forms one continuous projection history
- each receipt chain head matches the same captured Groundhog log prefix
- each projection and schema identity matches the configured relation registry
- each materialized relation has unique primary keys and the declared row count
- the snapshot produces valid Catalog relation metadata.

An older `FALLBACK` registry can remain after a registry migration.
Groundhog checks its reference, manifest, objects, and event receipt without applying the current relation schemas.

The JSON report includes a `query` object with its status, snapshot ID, event frontier, and counters.
A conclusive Query failure returns exit code 3 and a stable `query_*` failure code.

Query verification does not repair references or select `FALLBACK` after an invalid `CURRENT`.
Query-disabled verification keeps the log-only JSON report. S3 verification also keeps its existing report.

## Reports and exit status

Exit code 0 means the requested checks passed.
Exit code 3 means a stable failure code identifies the first conclusive violation.

Both results include one JSON report on standard output.

Exit code 1 identifies an operational error without a conclusive verification result.
Exit code 2 identifies invalid arguments or configuration.
Exit code 4 identifies an unsupported compatibility, security, or anchor requirement.

These results require different operator actions.
Do not treat them as one corrupt-log result.

## Orphans and remnants

Verification classifies an **orphan** as non-authoritative storage.
Examples include an unreferenced segment or private temporary file.

A **remnant** is incomplete final state that compatible writer recovery can exclude or repair.

Verification can succeed with either list populated.
The classification does not authorize deletion.
`verify --clean` is not available.

## Writer poisoning

The active writer stops mutation after a write failure with an uncertain outcome.

- The triggering request fails or loses a definitive result.
- Later mutation requests return 503.
- The active writer accepts no more appends.
- The service must close and reopen the directory through normal recovery.

After reopen, retry the original batch with the same key and content.
Recovery returns the existing receipt or commits the batch once.

## Operator procedure: verification failure

When `verify` returns exit code 3:

1. Stop mutations.
2. Preserve the JSON report and standard-error diagnostics.
3. Stop the live writer cleanly.
4. Preserve a filesystem copy before experimentation.
5. Record the binary identity and configuration.
6. Do not edit storage files or delete reported files.
7. Classify the stable failure code.
8. Compare the result with a known coherent backup.
9. Restore or investigate on an isolated copy.

For S3, preserve the prefix with IAM and bucket controls instead of making an unverified local copy.
Do not run the external test cleanup role against a production prefix.

A consumer rebuild cannot repair a corrupt Groundhog log.
It depends on readable authoritative history.

## Operator procedure: crash or poisoned writer

After a crash or HTTP 503 response:

1. Stop the old process.
2. Confirm that it no longer owns the socket or writer.
3. Restart `serve` with the same configuration.
4. Probe `GET /v1/streams` or a known replay request.
5. Retry ambiguous ingest with identical source, batch ID, and content.
6. Run `verify`.
7. Run `verify --chain` when the incident needs deeper evidence.

Do not remove `.lock`.
Let Groundhog reopen the directory through its recovery path.

For S3, a new session uses conditional HEAD updates to take over a stopped or failed writer. Do not
edit `HEAD.json` to bypass this process. If open reports authenticated corruption, stop all writers,
preserve the prefix, and use the stable verification code for investigation.

## Old warehouse files

Groundhog 0.3 ignores old warehouse files.
Their presence does not identify a log failure.

Do not delete them as part of log recovery.
Remove them only after the 0.3 upgrade passes verification, backup, and application checks.

## Restore validation

File presence does not prove a valid restore.
Use an isolated directory:

```sh
groundhog verify --config ./restored/groundhog.toml
groundhog verify --chain --config ./restored/groundhog.toml
groundhog serve --config ./restored/groundhog.toml
```

Serve the restore on an isolated socket.
Compare known replay events, stream counts, stream frontiers, and ingest receipts.

Do not connect the restore to production clients or share a writer path.

## See also

[`verify`](/groundhog/commands#verify),
[storage](/groundhog/concepts/storage),
[deployment operations](/groundhog/operations/deployment)

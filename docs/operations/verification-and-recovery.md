---
title: Verification and recovery
description: Verify a deployment and respond to startup, storage, and integrity failures.
---

<!-- generated-doc: GroundSystems/groundhog-src -->
> Source: [`GroundSystems/groundhog-src/docs-export/operations/verification-and-recovery.md`](https://github.com/GroundSystems/groundhog-src/blob/29b0fa4fc92fd4d4902533e4a714b1be97686eb9/docs-export/operations/verification-and-recovery.md) at [`29b0fa4fc92f`](https://github.com/GroundSystems/groundhog-src/commit/29b0fa4fc92fd4d4902533e4a714b1be97686eb9).
> Edit the source file. Do not edit this generated copy.


## Name

`groundhog-recovery`: verification depth, crash recovery, and operator response.

## Principles

Groundhog opens a data directory only when it can identify one authoritative durable history.
It refuses ambiguous or contradictory state.

Read-only commands do not repair data.
A writer open can finish recognized interrupted writes before it accepts new mutations.

Verification is always read-only.

## Ordinary open analysis

Every open checks these stored facts:

- a compatible storage format
- one coherent committed history frontier
- strictly ordered event ranges
- consistent durable `(source, batch_id)` commitments.

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

It compares chain heads at required boundaries and the captured frontier.
This check detects available-history alteration, insertion, removal, or reordering.

Local chain consistency does not prove that an owner did not replace the complete directory coherently.
Groundhog 0.2 does not support external anchors.

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

## Old warehouse files

Groundhog 0.2 ignores old warehouse files.
Their presence does not identify a log failure.

Do not delete them as part of log recovery.
Remove them only after the 0.2 upgrade passes verification, backup, and application checks.

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

[`verify`](/commands#verify),
[storage](/concepts/storage),
[deployment operations](/operations/deployment)

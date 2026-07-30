---
title: Getting started
description: Install Groundhog 0.2 and complete the first ingest, replay, follow, streams, and verification loop.
---

Run a local deployment through this loop:

```text
initialize -> serve -> ingest -> replay -> streams -> follow -> verify
```

This process creates a durable event log.
Applications use replay or follow to build their own derived views.

The examples use `curl` to show the HTTP interface.
An SDK or HTTP/1.1 client with Unix-socket support can use the same API.

## 1. Install the binary

Download an archive and checksum from [Groundhog releases](https://github.com/GroundSystems/groundhog/releases).
Published archives target Apple Silicon macOS and x86-64 Linux.

Each archive contains `groundhog`, `BUILD-INFO`, the Groundhog license, and third-party notices.

For version `0.2.0`:

```sh
VERSION=0.2.0
ARCHIVE="groundhog-${VERSION}-aarch64-apple-darwin.tar.gz"
curl -LO "https://github.com/GroundSystems/groundhog/releases/download/v${VERSION}/${ARCHIVE}"
curl -LO "https://github.com/GroundSystems/groundhog/releases/download/v${VERSION}/${ARCHIVE}.sha256"
shasum -a 256 -c "${ARCHIVE}.sha256"
tar -xzf "${ARCHIVE}"
sudo install -m 0755 groundhog /usr/local/bin/groundhog
groundhog --version
```

Use the version pinned by your application or deployment.
Groundhog uses Unix domain sockets and does not open a TCP port.

## 2. Initialize a deployment

```sh
groundhog init ./demo
```

Initialization creates:

```text
demo/
├── groundhog.toml
└── data/
    └── log/
```

Initialization writes `groundhog.toml` last and supports exact retries.
The same command validates the deployment without rewriting it.

Groundhog refuses conflicting files in paths that it owns.
It preserves unrelated sibling files in `demo/`.

See [`init`](/commands#init) for detailed retry and conflict behavior.

## 3. Review the configuration

The generated `groundhog.toml` is:

```toml
[data]
dir = "./data"

[security]
mode = "open"

[integrity]
anchor = "none"

[server]
socket = "data/ground.sock"
token = ""

[replay]
default_limit = 1000
max_limit = 100000
```

Relative paths resolve against the configuration file's directory.
They do not resolve against the process working directory.

An empty token disables HTTP authentication.
Set a token to require a bearer header on every request.

```toml
[server]
socket = "data/ground.sock"
token = "replace-with-a-secret"
```

Protect the configuration file because it stores the token as plaintext.

Groundhog 0.2 does not accept a `[query]` section.
Remove that section from a Groundhog 0.1 configuration before the upgrade.

See the [configuration reference](/references/configuration) for all fields.

## 4. Start the service

Run this command in one terminal:

```sh
groundhog serve --config ./demo/groundhog.toml
```

The process reports its socket path on standard error:

```text
serving ./demo/data/ground.sock
```

This line is not a readiness check.
Confirm readiness with a routed request:

```sh
curl --unix-socket ./demo/data/ground.sock http://ground/v1/streams
```

An empty log returns:

```json
{
  "v": 1,
  "streams": [],
  "next_after": null,
  "snapshot_through_event_id": null
}
```

HTTP/1.1 requires the URL host, but Groundhog ignores its value.

Stop the service with `Ctrl-C` or `SIGTERM`.
Graceful shutdown resolves queued mutations before it releases the writer.

## 5. Ingest an atomic batch

```sh
curl --unix-socket ./demo/data/ground.sock \
  -H 'Content-Type: application/json' \
  -d '{
    "v": 1,
    "batch_id": "example-contacts-001",
    "source": "example",
    "events": [
      {
        "stream": "contacts",
        "record_key": "contact-42",
        "kind": "upserted",
        "occurred_at": "2026-07-14T16:30:00Z",
        "payload": {"name": "Ada", "plan": "pro"}
      },
      {
        "stream": "contacts",
        "record_key": "contact-77",
        "kind": "upserted",
        "payload": {"name": "Lin", "plan": "starter"}
      }
    ]
  }' \
  http://ground/v1/events
```

A successful append returns a durable receipt:

```json
{
  "status": "committed",
  "batch_digest": "...",
  "events": 2,
  "first_event_id": "...",
  "last_event_id": "..."
}
```

Groundhog validates every event before it writes the atomic batch.
It adds event IDs, observation times, content hashes, and event hashes.

### Retry safely

The pair `(source, batch_id)` is the durable idempotency key.
Submit identical content with the same ID after a timeout or lost response.

- Identical content returns `status: "duplicate"` and the original event range.
- Different content with the same ID returns HTTP 409 and writes nothing.

Use a stable delivery, webhook, export, or synchronization ID.
Do not create a new ID only because a response was lost.

## 6. Replay durable history

Replay reads committed events directly from the log:

```sh
curl --unix-socket ./demo/data/ground.sock \
  'http://ground/v1/events?source=example&stream=contacts&limit=100'
```

The response contains matching events in increasing `event_id` order.
It also contains `next_after` and `snapshot_through_event_id`.

Persist `next_after` for the next finite replay request.
Use the same filters and add `after=<next_after>`.

A filtered empty page can still advance `next_after` across unrelated events.
Do not use `last_event_id` as the finite replay progress cursor.

## 7. Enumerate streams

`GET /v1/streams` reads authoritative stream summaries from the same durable log:

```sh
curl --unix-socket ./demo/data/ground.sock \
  'http://ground/v1/streams?source=example&limit=100'
```

Each row contains `source`, `stream`, `frontier_event_id`, and `event_count`.
The result order is source followed by stream.

For another page, send `next_after` as `after`.
Also send the first page's `snapshot_through_event_id` as `through`.

The anchor excludes later commits from the same logical enumeration.

## 8. Follow new commits

Add `follow=true` to keep the replay response open:

```sh
curl --no-buffer --unix-socket ./demo/data/ground.sock \
  'http://ground/v1/events?follow=true&source=example&stream=contacts'
```

The response uses newline-delimited JSON.
It sends initial `events` records, one `caught_up` record, and later live `events` records.

An `end` record identifies a clean or typed terminal condition.
EOF without an `end` record is a transport failure.

Persist the last delivered event ID.
Reconnect with that ID as the exclusive `after` cursor.

## 9. Build a derived view

Groundhog 0.2 does not include local SQL or a warehouse.
A consumer builds its own database, index, cache, or analytical model.

A durable consumer normally performs these actions:

1. Read finite replay from its saved `after` cursor.
2. Apply each event to the consumer's derived view.
3. Save the applied `event_id` in the same transaction when possible.
4. Start follow from the saved event ID after it catches up.
5. Reconnect and resume after any terminal or transport failure.

The consumer owns its derived-view schema and rebuild process.
It can reconstruct that state by replaying the Groundhog log again.

## 10. Verify and seal

Run structural verification while the service remains active:

```sh
groundhog verify --config ./demo/groundhog.toml
```

Run deep chain verification when you need all content commitments:

```sh
groundhog verify --chain --config ./demo/groundhog.toml
```

To seal the append tail into immutable Parquet segments:

```sh
# Stop serve first.
groundhog seal --config ./demo/groundhog.toml
groundhog serve --config ./demo/groundhog.toml
```

Sealing changes physical storage and does not change logical event history.

## Upgrade note

Groundhog 0.2 ignores old `warehouse.duckdb` files and never deletes them.
Remove them manually only after the 0.2 deployment opens, verifies, and passes application checks.

See [Deployment operations](/operations/deployment) for the complete upgrade procedure.

## Next steps

- Read the [HTTP API](/references/http-api) for replay, follow, streams, lifecycle, limits, and errors.
- Use the [Python SDK](/sdks/python) when an application does not need direct HTTP calls.
- Read [Storage](/concepts/storage) before you design backup and recovery procedures.
- Use [Verification and recovery](/operations/verification-and-recovery) for incident procedures.

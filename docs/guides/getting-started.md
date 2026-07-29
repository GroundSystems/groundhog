---
title: Getting started
description: Install Groundhog and complete the first ingest, replay, query, and verification loop.
---

Run a fresh local deployment through this operating loop:

```text
initialize -> serve -> ingest -> replay -> publish -> query -> verify
```

This produces a durable event log and a queryable warehouse snapshot. The examples use `curl` to
show the wire contract. An SDK or any HTTP/1.1 client that can connect to a Unix domain socket can
use the same API.

## 1. Install the binary

Download the versioned archive and checksum from the
[Groundhog releases](https://github.com/GroundSystems/groundhog/releases). Published archives
target Apple Silicon macOS and x86-64 Linux. Each archive contains `groundhog`, `BUILD-INFO`,
the Groundhog license, and third-party license notices.

For version `0.1.0`:

```sh
VERSION=0.1.0
ARCHIVE="groundhog-${VERSION}-aarch64-apple-darwin.tar.gz"
curl -LO "https://github.com/GroundSystems/groundhog/releases/download/v${VERSION}/${ARCHIVE}"
curl -LO "https://github.com/GroundSystems/groundhog/releases/download/v${VERSION}/${ARCHIVE}.sha256"
shasum -a 256 -c "${ARCHIVE}.sha256"
tar -xzf "${ARCHIVE}"
sudo install -m 0755 groundhog /usr/local/bin/groundhog
groundhog --version
```

Use the version pinned by your application or deployment. The service requires Unix domain
sockets and does not open a TCP port.

## 2. Initialize a deployment

```sh
groundhog init ./demo
```

Initialization creates:

```text
demo/
├── groundhog.toml
└── data/
    ├── log/
    └── warehouse.duckdb
```

The first warehouse is already valid and represents an empty log, so a new deployment is
immediately serveable. Initialization publishes `groundhog.toml` last and is retry-safe:
running the same command again validates the deployment and succeeds without rewriting it.
Conflicting Groundhog-owned files are refused rather than overwritten, while unrelated
siblings in `demo/` are preserved.

If `DIR` is omitted, `init` uses the current directory:

```sh
mkdir my-deployment
cd my-deployment
groundhog init
```

See [`init`](/commands#init) for the exact retry and conflict behavior.

## 3. Review the generated configuration

The generated `groundhog.toml` is local-first:

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

[query]
default_row_limit = 10000
max_row_limit     = 1000000
timeout           = "30s"

[replay]
default_limit = 1000
max_limit     = 100000
```

Relative paths resolve against the configuration file's directory, not the process working
directory. A deployment can therefore be invoked from anywhere:

```sh
groundhog serve --config /srv/example/groundhog.toml
```

`mode = "open"` is the supported security choice. Operations that would extend or attest history
support `anchor = "none"`; `serve`, `seal`, and `verify --chain` refuse a
signed/mirrored/witnessed requirement instead of silently claiming a weaker guarantee.

An empty token disables HTTP authentication. To require a bearer token, set one in the file and
include it on every request:

```toml
[server]
socket = "data/ground.sock"
token = "replace-with-a-secret"
```

```sh
curl --unix-socket ./demo/data/ground.sock \
  -H 'Authorization: Bearer replace-with-a-secret' \
  http://ground/v1/catalog
```

The token is stored directly in the configuration file, so protect that file with appropriate
filesystem permissions. See the [configuration reference](/references/configuration) for
every field and validation rule.

## 4. Start the service

Run this in one terminal:

```sh
groundhog serve --config ./demo/groundhog.toml
```

The process announces the socket path on standard error as it enters the serving path:

```text
serving ./demo/data/ground.sock
```

That human lifecycle line is not a readiness protocol. Confirm readiness with a real routed
request. The URL host in `curl` is syntactically required by HTTP/1.1 but ignored by
Groundhog, so this guide uses `http://ground`:

```sh
curl --unix-socket ./demo/data/ground.sock http://ground/v1/catalog
```

The initial response contains an empty `streams` array and the genesis warehouse receipt.

Stop the service with `Ctrl-C` or `SIGTERM`. Graceful shutdown stops admission, lets enqueued
mutations reach their real storage outcome, and then releases writer ownership.

## 5. Ingest an atomic event batch

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

The batch is atomic: Groundhog validates every event before writing any of them. It assigns
event IDs, observation times, content hashes, and event hashes.

### Retry safely

The pair `(source, batch_id)` is the durable idempotency key. If a request times out or loses its
response, submit the same batch again with the same ID:

- identical content returns `status: "duplicate"` and the original event range;
- different content under the same ID returns HTTP 409 and writes nothing.

Choose a stable batch ID from the source operation, such as a webhook delivery ID, export ID, or
sync-run ID. Do not generate a fresh ID merely because a response was lost.

The JSON ingest form accepts at most 10,000 events and 32 MiB per batch. The source name `system`
and batch IDs beginning with `groundhog/` are reserved for Groundhog.

## 6. Replay durable history

Replay reads the authoritative log directly, so committed events are visible without publishing
the warehouse:

```sh
curl --unix-socket ./demo/data/ground.sock \
  'http://ground/v1/events?source=example&stream=contacts&limit=100'
```

The optional filters are `after`, `source`, `stream`, `kind`, and `limit`; all filters are exact
matches. The response includes two cursor-like fields with different jobs:

- `last_event_id` is the last matching event returned;
- `next_after` is how far the scan progressed, including non-matching events.

Persist `next_after` when polling a filtered subscription. It lets an empty page advance past
unrelated history. Each response also reports `snapshot_through_event_id`, the coherent log
frontier captured for that request.

## 7. Publish the warehouse

Warehouse publication is explicit. Ingest updates the log; it does not automatically refresh SQL
relations or the catalog.

Leave `serve` running and execute:

```sh
groundhog project --config ./demo/groundhog.toml
```

`project` captures one coherent log snapshot and atomically publishes a complete warehouse. A
failed publication never displaces the last good generation. The running server adopts a new
generation between requests; an in-flight request
stays pinned to the generation it began with.

This produces two intentionally different freshness paths:

| interface | reads | freshness |
|---|---|---|
| replay | durable log | newly committed events immediately |
| query and catalog | published warehouse | through the last successful `project` or `rebuild` |

Receipts identify the exact published frontier and make the distinction observable.

## 8. Query with SQL

```sh
curl --unix-socket ./demo/data/ground.sock \
  -H 'Content-Type: application/json' \
  -d "{
    \"sql\": \"SELECT record_key, payload->>'name' AS name, payload->>'plan' AS plan FROM events WHERE source = 'example' AND stream = 'contacts' ORDER BY record_key, name, plan\",
    \"limit\": 100,
    \"timeout_secs\": 10
  }" \
  http://ground/v1/query
```

The warehouse publishes three queryable relations:

- `events`: fixed event columns through the published frontier;
- `meta.streams`: source/stream counts, observation times, and kinds; and
- `meta.projection_state`: receipt provenance for the generation.

Queries are confined to one read-only `SELECT` or `WITH` statement over published relations.
File/network access, extensions, mutations, volatile functions, and unsafe engine features are
rejected. A truncated result requires a total top-level `ORDER BY`; the simplest pattern is to
order by every selected column or use `ORDER BY ALL`.

Every successful result includes `columns`, `rows`, a `truncated` flag, and a `receipt` naming
the warehouse frontier, chain head, binary build, storage schema, and projection hash.

## 9. Discover data through the catalog

```sh
curl --unix-socket ./demo/data/ground.sock http://ground/v1/catalog
```

Narrow the result without SQL:

```sh
curl --unix-socket ./demo/data/ground.sock \
  'http://ground/v1/catalog?source=example&stream=contacts'
```

The catalog lists each published source/stream pair with its event count, first and last
observation times, and sorted event kinds. It carries the same snapshot receipt as a query.

## 10. Verify, seal, and rebuild

Run structural verification:

```sh
groundhog verify --config ./demo/groundhog.toml
```

Recompute payload and event hashes plus the full logical integrity chain:

```sh
groundhog verify --chain --config ./demo/groundhog.toml
```

Verification writes one JSON report to standard output and human diagnostics to standard error.
Exit 0 means every requested check passed; exit 3 means verification conclusively found a
storage violation.

To turn the appendable tail into immutable Parquet segments, stop `serve` and run:

```sh
groundhog seal --config ./demo/groundhog.toml
```

`seal` requires writer ownership and therefore cannot run while `serve` owns that writer. It
does not publish the warehouse and does not change logical events, order, IDs, or commitments.

To reconstruct the disposable warehouse from the durable log:

```sh
groundhog rebuild --config ./demo/groundhog.toml
```

`rebuild` can run while the service is live. It atomically publishes a replacement and subsequent
requests adopt it without restarting. Repeated rebuilds of the same frontier produce the same
logical relations and receipt; physical DuckDB bytes are not part of that promise.

## Common ways to use Groundhog

### Record connector output

A connector translates source changes into batches and submits them to `POST /v1/events`. Use the
source's delivery or sync identity as `batch_id`. Groundhog owns durable ordering,
idempotency, and integrity; the connector retains its source cursor and credentials.

### Build a replay consumer

Poll `GET /v1/events`, filter to the relevant source/stream/kind, and persist `next_after`.
Process business events using immutable `event_id` values. Each consumer owns its cursor outside
Groundhog, so consumers can move independently over the same history.

### Analyze a stable snapshot

Run `project` at a chosen operational boundary, use the catalog to discover streams, and send
confined SQL to `/v1/query`. Retain the returned receipt with reports or agent outputs when you
need to identify exactly which history produced them.

### Supervise it from an application

An application can launch a pinned `groundhog serve` child, wait for a successful routed
request over the configured socket, use the public HTTP contract, and stop it with `SIGTERM`.
This uses the same data directory and compatibility rules as an operator-managed service.

## Current binary capabilities

- local Unix socket only; no built-in TCP listener;
- `open` security mode and local anchor mode `none` only;
- JSON batch ingest only; no NDJSON stream or server-local path import;
- explicit full warehouse publication; no background or incremental refresh;
- no `current.*` state relations or deployment-defined projections;
- JSON query results only; and
- no CLI ingest, replay, query, or catalog wrappers. Use the HTTP API or an SDK.

Continue with [groundhog(1)](/references/cli), the
[HTTP API reference](/references/http-api), or [deployment operations](/operations/deployment).

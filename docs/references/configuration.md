---
title: groundhog.toml(5)
description: Complete configuration reference for one Groundhog deployment.
---

## Name

`groundhog.toml`: instance configuration for one Groundhog deployment.

## Description

Every command except `init` loads one TOML file selected by global option `--config`. The default
path is `./groundhog.toml`.

Configuration is validated before deployment data, locks, sockets, or warehouse publication is
opened or started. Unknown sections and keys are errors. A missing, unreadable, malformed, or
invalid file produces exit 2.

Relative filesystem paths resolve against the directory containing the configuration file. They
do not depend on the process working directory.

## Generated file

`groundhog init` currently writes:

```toml
[data]
dir = "./data"

[security]
mode = "open"              # open | governed | locked; this binary serves only "open"

[integrity]
anchor = "none"            # "none" is the supported level

[server]
socket = "data/ground.sock"   # the binary's only transport
token = ""                    # empty = no auth (local development)

[query]
default_row_limit = 10000
max_row_limit     = 1000000
timeout           = "30s"     # request default and maximum timeout_secs

[replay]
default_limit = 1000
max_limit     = 100000
```

Every section and key is optional when reading an existing file; omitted values receive the
defaults above.

## `[data]`

### `dir`

Filesystem path containing deployment data. Default: `./data`.

The durable log is `<dir>/log/`. The disposable published warehouse is
`<dir>/warehouse.duckdb`.

## `[security]`

### `mode`

One of:

- `open`: operator-readable local files and API access;
- `governed`: reserved for authenticated policy and audit enforcement; or
- `locked`: reserved for governed access plus encryption and external key custody.

Default: `open`.

The binary implements only `open`. All commands refuse `governed` and `locked` before touching
the log, warehouse, socket, or publication work. The refusal is exit 4; the
binary never silently weakens the configured mode.

## `[integrity]`

### `anchor`

One of `none`, `signed`, `mirrored`, or `witnessed`. Default: `none`.

The binary implements local consistency with `none`. `serve`, `seal`, and `verify --chain` refuse a
stronger configured requirement because those operations would otherwise overstate the anchor
guarantee. Read-only projection/rebuild and structural verification do not create or attest an
anchor and therefore do not engage that gate.

## `[server]`

### `socket`

Unix domain socket path bound by `serve`. Default: `data/ground.sock`.

The binary has no TCP-listener configuration. Remote or browser access must enter through an
operator-managed front door that connects to this socket.

### `token`

Bearer token required on every HTTP request. Default: the empty string.

An empty token disables authentication. A non-empty token requires:

```text
Authorization: Bearer <token>
```

The token is stored in plaintext TOML. Restrict configuration-file permissions and avoid placing
secrets in source control.

## `[query]`

### `default_row_limit`

Positive integer used when a query omits `limit`. Default: `10000`.

### `max_row_limit`

Positive maximum accepted request `limit`. Default: `1000000`.

`default_row_limit` must not exceed `max_row_limit`.

### `timeout`

Positive duration used both as the default and the maximum accepted request `timeout_secs`.
Default: `30s`.

Durations use a positive integer followed by one unit:

- `s`: seconds;
- `m`: minutes;
- `h`: hours; or
- `d`: days.

Examples: `5s`, `15m`, `1h`, `2d`. Fractional values, compound values such as `1m30s`, unknown
units, zero, and overflow are invalid.

## `[replay]`

### `default_limit`

Positive matching-event limit used when replay omits `limit`. Default: `1000`.

### `max_limit`

Positive maximum accepted replay `limit`. Default: `100000`.

`default_limit` must not exceed `max_limit`.

## Path example

Given `/srv/acme/groundhog.toml`:

```toml
[data]
dir = "./state"

[server]
socket = "run/ground.sock"
```

the resolved paths are:

```text
/srv/acme/state
/srv/acme/run/ground.sock
```

They remain the same when the process is launched from another working directory.

## Reload behavior

Configuration is loaded when a command begins. `serve` does not live-reload the file. Restart the
service to apply token, socket, query-bound, or replay-bound changes.

Changing `data.dir` points a subsequent command at another deployment; it does not migrate data.

## Unsupported keys

Use only the fields documented on this page. Unknown sections and keys are rejected rather than
ignored.

## See also

[groundhog(1)](/references/cli),
[`init`](/commands#init),
[`serve`](/commands#serve),
[deployment operations](/operations/deployment)

---
title: Configuration
description: All fields accepted by Groundhog 0.2 in groundhog.toml.
---

<!-- generated-doc: GroundSystems/groundhog-src -->
> Source: [`GroundSystems/groundhog-src/docs-export/references/configuration.md`](https://github.com/GroundSystems/groundhog-src/blob/29b0fa4fc92fd4d4902533e4a714b1be97686eb9/docs-export/references/configuration.md) at [`29b0fa4fc92f`](https://github.com/GroundSystems/groundhog-src/commit/29b0fa4fc92fd4d4902533e4a714b1be97686eb9).
> Edit the source file. Do not edit this generated copy.


Groundhog reads one TOML file for each deployment.
The default path is `./groundhog.toml`.

Pass another path with the global `--config <PATH>` option.
Relative paths in the file resolve against the file's directory.

Groundhog validates configuration before it opens deployment data, locks, or sockets.
Unknown sections and keys are errors.

## Generated configuration

`groundhog init` writes this file:

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

## `[data]`

### `dir`

The directory that contains Groundhog data.
Default: `./data`.

The durable log is `<dir>/log/`.
Groundhog 0.2 does not use a warehouse path.

## `[security]`

### `mode`

The configured security contract.
Default: `open`.

Accepted names are `open`, `governed`, and `locked`.
Groundhog 0.2 serves only `open`.
It refuses other values with exit code 4 before it opens deployment state.

## `[integrity]`

### `anchor`

The configured chain-head anchoring contract.
Default: `none`.

Accepted names are `none`, `signed`, `mirrored`, and `witnessed`.
Groundhog 0.2 supports only `none`.
It refuses stronger modes with exit code 4.

## `[server]`

### `socket`

The Unix domain socket used by `serve`.
Default: `data/ground.sock`.

The service does not listen on TCP.
Clients need filesystem access to this socket.

### `token`

The bearer token required for every HTTP request.
Default: an empty string.

An empty token disables HTTP authentication.
A non-empty token requires this header:

```text
Authorization: Bearer <token>
```

The file stores the token as plaintext TOML.
Restrict file permissions and do not commit secrets to source control.

## `[replay]`

### `default_limit`

The matching-event limit used when finite replay omits `limit`.
Default: `1000`.

### `max_limit`

The largest accepted finite replay `limit`.
Default: `100000`.

Both values must be positive.
`default_limit` cannot exceed `max_limit`.

Follow mode uses these values as page limits within one open response.
The limit does not end the follow response.

## Upgrade from 0.1

Groundhog 0.2 rejects the removed `[query]` section.
Remove the complete section before starting a 0.2 command.

The exact error is:

```text
The [query] section is no longer supported. Remove it from groundhog.toml.
```

Do not replace this section with another warehouse setting.
Groundhog 0.2 stores and serves only the durable event log.

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

These paths do not depend on the process working directory.

## Reload behavior

Groundhog loads configuration when a command starts.
`serve` does not reload the file while it runs.

Restart the service to apply token, socket, or replay-limit changes.
Changing `data.dir` selects another deployment and does not move data.

## See also

[groundhog(1)](/references/cli),
[`init`](/commands#init),
[`serve`](/commands#serve),
[deployment operations](/operations/deployment)

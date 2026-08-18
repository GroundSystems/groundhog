# Groundhog

Groundhog provides downloads, user documentation, and a published interface.
The private `GroundSystems/groundhog-src` repository contains the canonical Groundhog source.

Groundhog 0.3 stores and serves a durable append-only event log. An optional local Query service
adds typed indexed reads over immutable snapshots. The current binary exposes the built-in
`groundhog.events` relation, Catalog metadata, the JSON Query API, and matching CLI commands.
Groundhog does not include SQL or a warehouse.

## Support and feature requests

Use [GitHub Issues](https://github.com/GroundSystems/groundhog/issues) for support requests and
feature requests. The public repository does not use GitHub Projects.

## Install with Homebrew

```sh
brew install GroundSystems/groundhog/groundhog
```

[`GroundSystems/homebrew-groundhog`](https://github.com/GroundSystems/homebrew-groundhog)
maintains the formula.

## Direct downloads

Versioned Apple Silicon macOS and x86-64 Linux archives and their SHA-256 checksums are published
under [GitHub Releases](https://github.com/GroundSystems/groundhog/releases). Every archive includes
the `groundhog` binary, build provenance, dependency roots, licenses, the OpenAPI contract,
projection contracts, and conformance fixtures.

## Documentation

The [Groundhog manual](https://github.com/GroundSystems/groundhog/tree/main/docs) is published from
`GroundSystems/groundhog`. That repository owns its guides, navigation, branding, and Mintlify
deployment.

The private source repository owns the reference pages under
[`docs/groundhog/`](https://github.com/GroundSystems/groundhog-src/tree/main/docs/groundhog).
Buildkite copies that path to the same path in the public repository.

## Published interface and verification

[`openapi.yaml`](openapi.yaml) is the authoritative HTTP contract. The [`verify/`](verify/)
directory contains public conformance tools, black-box checks, and compatibility fixtures.

## License

The [Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md) covers the
documentation and other repository contents. Release archives contain the license and third-party
notices applicable to the included binary.

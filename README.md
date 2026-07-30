# Groundhog

This public repository provides Groundhog downloads, user documentation, and published
contracts. The private [`GroundSystems/groundhog-src`](https://github.com/GroundSystems/groundhog-src)
repository contains the canonical Groundhog source.

Groundhog 0.2 stores and serves a durable append-only event log. Applications use replay or
follow to build their own derived views. Groundhog does not include local SQL or a warehouse.

## Support and feature requests

Use [GitHub Issues](https://github.com/GroundSystems/groundhog/issues) for support requests
and feature requests. This public repository does not use GitHub Projects.

## Install with Homebrew

```sh
brew install GroundSystems/groundhog/groundhog
```

[`GroundSystems/homebrew-groundhog`](https://github.com/GroundSystems/homebrew-groundhog)
maintains the formula.

## Direct downloads

Versioned Apple Silicon macOS and x86-64 Linux archives and their SHA-256 checksums are
published under [GitHub Releases](https://github.com/GroundSystems/groundhog/releases).
Every archive includes the `groundhog` binary, build provenance, the Groundhog license, and
third-party license notices.

## Documentation

This repository maintains the Groundhog manual in [`docs/`](docs/). Its `docs.json` configuration is ready
for a Mintlify deployment using `/docs` as the documentation path.

## Published contract

The private `GroundSystems/groundhog-src` repository generates the [`spec/`](spec/) contract and
[`tests/test-vectors/`](tests/test-vectors/) compatibility vectors. Do not edit these published
copies directly. [`spec/publication-manifest.json`](spec/publication-manifest.json) lists every
file selected for publication.

## License

The [Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md) covers the
documentation and other repository contents. Release archives
contain the license and third-party notices applicable to the included binary.

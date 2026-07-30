# Groundhog

Groundhog provides downloads, user documentation, and a published interface.
The private `GroundSystems/groundhog-src` repository contains the canonical Groundhog source.

Groundhog 0.2 stores and serves a durable append-only event log. Applications use replay to build
their own derived views. Groundhog does not include local SQL or a warehouse.

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
the `groundhog` binary, build provenance, the Groundhog license, and third-party license notices.

## Documentation

The Groundhog manual is in [`docs/`](docs/). Its `docs.json` configuration uses `/docs` as the
documentation path for Mintlify.

## Published interface and verification

[`openapi.yaml`](openapi.yaml) is the authoritative HTTP contract. The [`verify/`](verify/)
directory contains public conformance tools, black-box checks, and compatibility fixtures.

## License

The [Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md) covers the
documentation and other repository contents. Release archives contain the license and third-party
notices applicable to the included binary.

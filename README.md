# Groundhog

This public repository provides Groundhog downloads, user documentation, and published
contracts. The private [`GroundSystems/groundhog-src`](https://github.com/GroundSystems/groundhog-src)
repository contains the canonical Groundhog source.

## Support and feature requests

Use [GitHub Issues](https://github.com/GroundSystems/groundhog/issues) for support requests
and feature requests. This public repository does not use GitHub Projects.

## Install with Homebrew

```sh
brew install GroundSystems/groundhog/groundhog
```

The formula is maintained in
[`GroundSystems/homebrew-groundhog`](https://github.com/GroundSystems/homebrew-groundhog).

## Direct downloads

Versioned Apple Silicon macOS and x86-64 Linux archives and their SHA-256 checksums are
published under [GitHub Releases](https://github.com/GroundSystems/groundhog/releases).
Every archive includes the `groundhog` binary, build provenance, the Groundhog license, and
third-party license notices.

## Documentation

The Groundhog manual is maintained in [`docs/`](docs/). Its `docs.json` configuration is ready
for a Mintlify deployment using `/docs` as the documentation path.

## Published contract

The [`spec/`](spec/) contract and [`tests/test-vectors/`](tests/test-vectors/) compatibility
vectors are generated copies from `GroundSystems/groundhog-src`. Do not edit these published
copies directly. [`spec/publication-manifest.json`](spec/publication-manifest.json) lists every
file selected for publication.

## License

The documentation and other repository contents are licensed under the
[Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md). Release archives
contain the license and third-party notices applicable to the included binary.

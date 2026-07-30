# Groundhog verification

This directory contains public tools and fixtures for independent Groundhog verification. The
tools use public interfaces and do not import the Groundhog implementation.

## HTTP conformance

[`conformance/`](conformance/) validates the authoritative `openapi.yaml` file. The default
command checks the document structure, operations, examples, schemas, errors, and headers:

```sh
python3 -m verify.conformance
```

Add `--binary` to run the same contract against a local Groundhog binary:

```sh
python3 -m verify.conformance --binary /path/to/groundhog
```

The [conformance README](conformance/README.md) lists the pinned dependencies and self-tests.

## Compatibility vectors

[`vectors/`](vectors/) contains stable fixtures for serialized bytes, hashes, lifecycle rules, and
conditional append rules. Run the standard-library verifier from the repository root:

```sh
python3 verify/vectors/verify.py
```

The [vector README](vectors/README.md) describes each fixture and its compatibility requirements.

## Black-box checks

[`blackbox/`](blackbox/) checks an external `groundhog` binary through its command-line and Unix
socket interfaces. The checks record operation histories and verify valid sequential outcomes.

Run all executable scenarios from the repository root:

```sh
python3 -m verify.blackbox \
  --binary /path/to/groundhog \
  --output /path/to/verification-output
```

The command runs append, retirement race, replay, and stream pagination scenarios. It writes each
operation history to the output directory and prints one JSON summary to standard output.

Run the black-box self-tests with deterministic discovery:

```sh
python3 -m unittest discover \
  -s verify/blackbox/tests \
  -t . \
  -p 'test_*.py'
```

Set `GROUNDHOG_BIN` to include the external-binary test in that self-test command:

```sh
GROUNDHOG_BIN=/path/to/groundhog \
  python3 -m unittest discover \
  -s verify/blackbox/tests \
  -t . \
  -p 'test_*.py'
```

## Deterministic self-tests

The self-tests use temporary directories and fixed seeds. They do not import Rust packages or use
private test modules.

```sh
python3 -m unittest discover -s verify/conformance/tests -t . -p 'test_*.py'
python3 -m unittest discover -s verify/blackbox/tests -t . -p 'test_*.py'
```

# OpenAPI conformance

The static validator checks `openapi.yaml` without a Groundhog process. It checks
the OpenAPI structure, local references, operations, examples, schemas, errors,
statuses, media types, and headers.

Create an isolated Python environment and run these commands from the repository
root:

```sh
python3 -m venv .venv-verify
.venv-verify/bin/python -m pip install -r verify/requirements.txt
.venv-verify/bin/python -m verify.conformance
.venv-verify/bin/python -m unittest discover -s verify/conformance/tests -t . -p 'test_*.py'
```

The validator does not import Groundhog implementation code. It does not use
network references. Every `$ref` in the public document must resolve locally.

Build the binary and run the live Unix-socket checks:

```sh
cargo build --locked
.venv-verify/bin/python -m verify.conformance --binary target/debug/groundhog
```

The default live run keeps Query disabled and verifies the base event-log API. Add `--query` to
start a second authenticated local deployment and validate Query and Catalog responses against the
public schemas:

```sh
.venv-verify/bin/python -m verify.conformance \
  --binary target/debug/groundhog --query
```

The Query option is local-only. The Query-enabled live checks test projected relations, live
catch-up, aggregates, limits, atomic multi-query errors, and cursors.

The live checks create one disposable deployment under `/private/tmp`. They check
successes, errors, pagination, follow, retirement, and successor lineage. They also
send raw duplicate-member JSON and malformed query strings.

Use `--history` to record compatible finite operations with the public black-box
history recorder. The live verifier checks the recorded sequential history before
it exits:

```sh
.venv-verify/bin/python -m verify.conformance \
  --binary target/debug/groundhog --history /tmp/openapi-history.json
```

The recorder integration does not run or copy black-box scenarios. It records the
finite operations that the OpenAPI conformance checks already perform.

To run the same contract against S3, use one unique no-delete parent prefix. The harness adds a
random child for each process that it starts:

```sh
python3 -m verify.conformance \
  --binary target/debug/groundhog \
  --backend s3 \
  --s3-bucket company-groundhog \
  --s3-region us-west-2 \
  --s3-prefix groundhog-tests/2026-08-11-001
```

This live S3 command is deferred. Compile and local test coverage do not count as live evidence.

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

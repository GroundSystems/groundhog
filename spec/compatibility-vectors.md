# Compatibility Vector Contract

The files under `tests/test-vectors/` are known-answer fixtures for contract version 1. Their
relative paths and bytes are part of the published compatibility contract.

## Required coverage

The published vector set covers these rules:

| File | Rule |
| --- | --- |
| `jcs.json` | RFC 8785 output, binary64 cases, I-JSON rejection, and nesting limit |
| `content_hash.json` | canonical payload bytes and SHA-256 |
| `envelope.json` | canonical event envelopes and event hashes |
| `batch_digest.json` | ordered batch commitment and digest |
| `chain.json` | genesis and ordered chain folds |
| `format_record.txt` | exact stable manifest format record |
| `tail_one_batch.ndjson` | exact tail framing bytes for one batch |
| `seal_manifest_record.txt` | exact seal manifest record bytes |
| `segment.parquet` | one compliant version 1 segment |
| `segment_expected.json` | the segment file commitment, schema facts, and logical rows |
| `lifecycle.json` | retirement and successor-lineage bytes, hashes, and ordering rules |
| `stream_precondition.json` | conditional append outcomes and precondition digest exclusion |
| `verify.py` | independent vector verifier |

The Parquet fixture certifies one compliant file. A compatible writer does not need to reproduce
its bytes for newly written segments.

A compatible reader MUST extract the expected schema and logical rows from the fixture. It MUST
also confirm the fixture file hash against `segment_expected.json`.

## Independent checks

The Rust vector test MUST read the committed fixtures and compare the implementation with every
known answer.

The Python verifier MUST use only the Python standard library and fixture bytes. It MUST NOT import
or call Groundhog implementation code.

Run both checks from the repository root:

```sh
cargo test --locked --test vectors
python3 tests/test-vectors/verify.py
```

An implementation that claims storage schema version 1 MUST pass all applicable vector checks. An
SDK that does not read storage MUST pass applicable event, batch, and cursor contract tests.

## Vector changes

A known-answer change is a compatibility change. A contributor MUST NOT update expected output
only to make an implementation test pass.

A change to an existing vector requires all these items:

1. Explain the externally observable behavior change.
2. Identify each affected contract and storage version.
3. Update the specification and implementation in the same release change.
4. Update the independent verifier when its interpretation changes.
5. Derive the new answer independently from the implementation under test.

An additive vector can keep the contract version when it only tests an existing requirement. A
changed accepted byte sequence requires the version change defined by the affected contract.

The public repository MUST receive the exact vector files selected in
[`publication-manifest.json`](publication-manifest.json). Publication MUST NOT regenerate or
reformat them.

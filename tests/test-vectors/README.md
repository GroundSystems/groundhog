# Executable compatibility vectors

This directory contains known-answer fixtures for Groundhog's executable compatibility contract.
The fixtures cover stable bytes, hashes, lifecycle rules, and conditional append rules.

The byte-format fixtures have two independent checks:

1. `tests/vectors.rs` reads the committed fixtures and verifies the Rust implementation against
   them.
2. `verify.py` uses only the Python standard library and no Groundhog code. It checks every
   byte-format fixture. The Rust test also checks the Parquet schema and logical rows.

The Python verifier also checks the lifecycle and conditional append vectors.

## Lifecycle vector

`lifecycle.json` defines one ordered predecessor, retirement, and successor history. It fixes these
expected values:

- canonical lifecycle payload bytes
- content hashes and event-envelope hashes
- deterministic retirement batch identity
- batch digest preimages and tail-line bytes
- source-retirement and successor-lineage relationships
- integrity-chain heads after each event

The successor marker has position zero in the successor source's first batch. It references the
exact retired predecessor frontier.

## Conditional append vector

`stream_precondition.json` defines request variants with different stream-frontier preconditions.
Every variant has the same submitted events and batch digest.

The vector proves that `stream_precondition` is admission metadata. The batch digest excludes the
precondition.

Independent scenarios cover exact matches, mismatches, null frontiers, duplicate retries, and
conflicting retries. A failed precondition does not reserve the batch ID.

Run both checks from the repository root:

```sh
cargo test --locked --test vectors
python3 tests/test-vectors/verify.py
```

## Changing a vector

A vector change is a compatibility change, not routine fixture regeneration. A pull request that
changes a committed vector must:

1. Explain which accepted behavior changed and why.
2. Identify the affected format or schema versions.
3. Update the Rust implementation and tests in the same change.
4. Update the independent verifier when its interpretation changes.
5. Show that an independent process derived the new values without using the code under test.

Do not update expected values solely to make a failing implementation pass.

# Local Storage Format

This document defines local storage schema version 1. Groundhog Cloud does not need to use this
format.

## Version identity

The durable format identifier is `groundhog/log`. The current `schema_version`, `min_reader`, and
`min_writer` are all 1.

A compatible reader MUST refuse an unknown schema version. It MUST NOT infer a format from similar
fields or file names.

A reader below `min_reader` MUST refuse the directory. A compatible reader below `min_writer` MAY
open the log read-only but MUST NOT mutate it.

A storage change MUST increase `schema_version` when a reader needs new interpretation rules.

## Directory layout

The durable log is the `log/` directory under the configured data directory:

```text
log/
├── manifest.jsonl
├── tail.ndjson
├── pending/
└── segments/
```

`manifest.jsonl`, `tail.ndjson`, `pending/`, and `segments/` are required entries. The warehouse
file is derived state and is not part of the durable log.

The logical log concatenates these inputs in increasing `event_id` order:

1. active segments from the manifest
2. uncovered pending generations
3. the committed prefix of the active tail

The complete order MUST be strictly increasing. Ranges MUST NOT overlap or regress.

## Manifest framing

`manifest.jsonl` is append-only. Each committed record is RFC 8785 canonical JSON encoded as UTF-8
and followed by exactly one LF byte.

A record MUST NOT contain a BOM or CR. Blank records are invalid.

The first committed record MUST be this exact JSON body:

```json
{"format_id":"groundhog/log","min_reader":1,"min_writer":1,"schema_version":1,"stability":"stable","type":"format"}
```

The body and its LF are separate durable phases. The writer fsyncs the body before it appends and
fsyncs the LF commit marker.

A final body without LF is uncommitted. A compatible writer can truncate it during recovery. A
malformed LF-terminated record is corruption.

## Tail records

`tail.ndjson` contains one event per line. An empty tail is a zero-byte file.

Each line is RFC 8785 canonical JSON followed by one LF. The object contains every committed event
field plus `batch_len` and `batch_digest`.

`batch_len` is the positive event count in the committed batch. `batch_digest` is the digest from
[`append.md`](append.md).

Every line in one batch repeats the same `batch_len` and `batch_digest`. The batch occupies one
consecutive run of lines with one source and batch ID.

`batch_len` and `batch_digest` are tail framing. They do not enter the canonical event envelope or
integrity chain. A segment omits both fields.

The writer appends all batch lines and fsyncs the tail. That fsync is the batch commit point.

Recovery admits only complete batches with valid framing, digests, hashes, and order. A torn final
batch is an uncommitted remnant that a compatible writer can truncate.

Malformed content before the final incomplete batch is corruption. Recovery MUST NOT accept or
repair a complete batch with a digest mismatch.

The exact tail bytes for one batch are in `tests/test-vectors/tail_one_batch.ndjson`.

## Pending generations

Rotation renames a non-empty tail into this exact path:

```text
pending/<first_event_id>_<last_event_id>.ndjson
```

The IDs use canonical hyphenated UUIDv7 text. The file keeps the exact tail record bytes.

Rotation fsyncs the old tail before the rename. It then creates and fsyncs a new zero-byte
`tail.ndjson`.

A pending generation is authoritative until a committed manifest record covers its exact range. A
covered pending file is a removable remnant, not a second copy of the log.

## Segment files

A seal converts one pending generation into an immutable Parquet segment. The final path is:

```text
segments/<first_event_id>_<last_event_id>_<sha256>.parquet
```

`sha256` is lowercase hexadecimal SHA-256 over the complete segment file bytes. The manifest path
MUST equal the path implied by its range and file hash.

Segment rows MUST be strictly increasing by `event_id`. The segment range and row count MUST match
the manifest record.

The Parquet schema contains one required group named `event` with these columns in this order:

| Column | Parquet physical and logical type | Repetition | Stored value |
| --- | --- | --- | --- |
| `event_id` | `FIXED_LEN_BYTE_ARRAY(16)`, UUID | required | RFC 9562 network-order bytes |
| `source` | `BYTE_ARRAY`, UTF8 | required | event string |
| `stream` | `BYTE_ARRAY`, UTF8 | required | event string |
| `record_key` | `BYTE_ARRAY`, UTF8 | required | event string |
| `kind` | `BYTE_ARRAY`, UTF8 | required | event string |
| `occurred_at` | `BYTE_ARRAY`, UTF8 | optional | accepted timestamp text |
| `observed_at` | `BYTE_ARRAY`, UTF8 | required | canonical timestamp text |
| `payload` | `BYTE_ARRAY`, UTF8 | required | RFC 8785 canonical JSON text |
| `content_hash` | `BYTE_ARRAY`, UTF8 | required | lowercase hash |
| `batch_id` | `BYTE_ARRAY`, UTF8 | required | event string |
| `event_hash` | `BYTE_ARRAY`, UTF8 | required | lowercase hash |

The schema does not require one byte-identical Parquet encoding. A writer MAY choose valid Parquet
encoding details and MUST commit the resulting file hash.

## Segment manifest record

A version 1 seal appends a closed `segment` record. It contains these members:

- `type` equal to `segment`
- `schema_version` equal to 1
- `path` equal to the implied segment path
- `first_event_id` and `last_event_id`
- positive `events`
- lowercase `sha256`
- `head` at `last_event_id`
- `sealed_at` in `YYYY-MM-DDTHH:MM:SS.dddZ` form
- `batches` with the original batch partition

Each `batches` item contains `source`, `batch_id`, `batch_digest`, `events`,
`first_event_id`, and `last_event_id`.

The batch items MUST be ordered, non-overlapping, and non-empty. Their counts and ranges MUST
partition every segment row exactly once.

`sealed_at` is operational metadata. It does not define log order or enter the integrity chain.

Version 1 does not support manifest records with `replaces`. A compatible version 1 runtime MUST
refuse a directory that contains a compaction record.

The seal first publishes and fsyncs the segment file. It then appends and fsyncs the manifest body.
The manifest LF fsync is the seal commit point.

Before that point, the pending generation is authoritative. After that point, the segment is
authoritative.

## Hashes and chain

The content, event, and batch hashes follow [`event.md`](event.md) and [`append.md`](append.md).

The genesis preimage is the ASCII bytes of `groundhog/genesis/v1` without a newline:

```text
head_0 = SHA-256("groundhog/genesis/v1")
```

For each event in log order, Groundhog computes:

```text
head_n = SHA-256(raw_32_bytes(head_n-1) || raw_32_bytes(event_hash_n))
```

Each segment manifest record stores the chain head at its last event. Verification recomputes the
payload hash, event hash, and chain before it accepts that head.

## Recovery and verification

Every open MUST exclude uncommitted manifest and tail remnants. A read-only open MUST NOT apply a
repair.

A writer applies allowed repairs under the exclusive writer lock. It MUST fsync each repair and
repeat analysis before it accepts a mutation.

An uncertain write, fsync, rename, or truncate outcome poisons that writer session. The session
MUST NOT acknowledge or accept another mutation. Reopen performs recovery.

Normal open checks structure, required files, manifest ranges, Parquet schema, and footer row
counts. It does not recompute every segment file hash.

Full verification recomputes segment file hashes and validates actual ordered rows. Chain
verification also recomputes content hashes, event hashes, lifecycle state, and all chain heads.

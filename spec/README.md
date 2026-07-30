# Groundhog Contract

This directory defines Groundhog's externally observable contract.

`GroundSystems/groundhog-src` is the canonical source for this contract. The public
`GroundSystems/groundhog` repository receives an exact selected copy at publication time.

The Rust implementation, SDKs, verification tools, and Groundhog Cloud must conform to the
published contract version. Each component must claim its supported version.

## Normative language

Capitalized requirement terms have the meanings from RFC 2119 and RFC 8174. These terms include
MUST, SHOULD, MAY, REQUIRED, RECOMMENDED, and their negative forms.

Examples explain the requirements but do not replace them. JSON schemas supplement the written
requirements. The written requirements control if a schema and the prose disagree.

Implementation documentation can define internal behavior. It cannot change this contract.

## Contract versions

The contract uses one positive integer version. Version 1 is the current version.

An additive change can keep the current version. An additive change can add an optional request
member, an optional response member, or a new error code.

A change MUST use a new contract version if it changes accepted input or required output. A new
version is also required if a change weakens a durability, ordering, or snapshot guarantee.

The storage schema has an independent `schema_version`. A storage change MUST increase that
version when a reader needs new interpretation rules.

## Shared contract

The shared contract covers these durable operations:

- event and batch validation
- atomic append and idempotency
- stream-frontier preconditions
- source retirement and successor lineage
- finite replay responses
- durable stream enumeration

The local runtime and Groundhog Cloud MAY use different internal storage and deployment systems.
Both implementations MUST preserve the shared external behavior.

Authentication, authorization, tenancy, deployment, backup, and connector management are outside
the shared contract. An implementation MAY add these functions around the shared operations.

## Local storage contract

The storage contract applies only to compatible local Groundhog data directories. It does not
require Groundhog Cloud to use the same storage format.

## Publication

[`publication-manifest.json`](publication-manifest.json) selects every public contract file. A
publication process MUST copy each selected file without content changes.

The process MUST also copy every selected compatibility vector from `tests/test-vectors/`. The
relative path of each copied file MUST stay unchanged.

The public copy is informative about its source. `groundhog-src` remains the normative authority.

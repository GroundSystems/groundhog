#!/usr/bin/env python3
"""Validate the public Groundhog OpenAPI contract and all embedded examples."""

from __future__ import annotations

import argparse
import json
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml
from openapi_schema_validator import OAS32Validator
from openapi_spec_validator import validate as validate_openapi

JsonObject = dict[str, Any]
HTTP_METHODS = {"get", "head", "post", "put", "patch", "delete", "options", "trace"}
DIALECT = "https://spec.openapis.org/oas/3.2/dialect/2025-09-17"

EXPECTED_OPERATIONS: dict[tuple[str, str], tuple[str, set[str], str]] = {
    ("/v1/events", "post"): (
        "appendEvents",
        {"200", "400", "401", "409", "413", "415", "429", "500", "503"},
        "#/components/parameters/NoQuery",
    ),
    ("/v1/events", "get"): (
        "replayEvents",
        {"200", "400", "401", "429", "500"},
        "#/components/parameters/ReplayQuery",
    ),
    ("/v1/events", "head"): (
        "inspectReplay",
        {"200", "400", "401", "429", "500"},
        "#/components/parameters/ReplayQuery",
    ),
    ("/v1/streams", "get"): (
        "listStreams",
        {"200", "400", "401", "429", "500"},
        "#/components/parameters/StreamsQuery",
    ),
    ("/v1/streams", "head"): (
        "inspectStreams",
        {"200", "400", "401", "429", "500"},
        "#/components/parameters/StreamsQuery",
    ),
    ("/v1/sources/retire", "post"): (
        "retireSource",
        {"200", "400", "401", "404", "413", "415", "429", "500", "503"},
        "#/components/parameters/NoQuery",
    ),
}

REQUEST_SCHEMAS = {
    ("/v1/events", "post"): "#/components/schemas/AppendBatch",
    ("/v1/sources/retire", "post"): "#/components/schemas/RetirementRequest",
}

ERROR_STATUSES = {
    "invalid_request": 400,
    "invalid_batch": 400,
    "invalid_events": 400,
    "invalid_source_retirement": 400,
    "invalid_source_lineage": 400,
    "invalid_replay_request": 400,
    "invalid_streams_request": 400,
    "stream_anchor_unavailable": 400,
    "unauthorized": 401,
    "not_found": 404,
    "source_not_found": 404,
    "method_not_allowed": 405,
    "batch_id_conflict": 409,
    "source_retired": 409,
    "source_lineage_conflict": 409,
    "stream_frontier_conflict": 409,
    "body_too_large": 413,
    "unsupported_media_type": 415,
    "overloaded": 429,
    "internal_error": 500,
    "writer_poisoned": 503,
}

RETAINED_SCHEMAS = {
    "AppendBatch",
    "AppendReceipt",
    "Error",
    "Event",
    "LineagePayload",
    "ReplayResponse",
    "RetirementPayload",
    "RetirementRequest",
    "RetirementResponse",
    "StreamsResponse",
}


class ContractError(ValueError):
    """The OpenAPI contract failed one or more conformance checks."""


class UniqueKeyLoader(yaml.SafeLoader):
    """A safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> JsonObject:
    mapping: JsonObject = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ContractError(f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_document(path: Path) -> JsonObject:
    """Load one YAML OpenAPI document and reject duplicate mapping keys."""
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ContractError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError("the OpenAPI document root must be an object")
    return value


def _pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def resolve_local(document: JsonObject, reference: str) -> Any:
    """Resolve one local JSON Pointer reference."""
    if not reference.startswith("#/"):
        raise ContractError(f"reference is not local: {reference}")
    current: Any = document
    for raw_token in reference[2:].split("/"):
        token = _pointer_token(raw_token)
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ContractError(f"unresolved local reference: {reference}")
    return current


def dereference(document: JsonObject, value: Any) -> Any:
    """Follow a chain of local Reference Objects."""
    seen: set[str] = set()
    while isinstance(value, Mapping) and isinstance(value.get("$ref"), str):
        reference = value["$ref"]
        if reference in seen:
            raise ContractError(f"cyclic Reference Object: {reference}")
        seen.add(reference)
        value = resolve_local(document, reference)
    return value


def _walk(value: Any, location: str = "$") -> Iterator[tuple[str, Any]]:
    yield location, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk(child, f"{location}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{location}/{index}")


def _operations(document: JsonObject) -> Iterator[tuple[str, str, JsonObject]]:
    paths = document.get("paths")
    if not isinstance(paths, Mapping):
        return
    for path, path_item in paths.items():
        if not isinstance(path_item, Mapping):
            continue
        for method, operation in path_item.items():
            if method in HTTP_METHODS and isinstance(operation, dict):
                yield str(path), method, operation


def _schema_wrapper(document: JsonObject, schema: Any) -> JsonObject:
    return {
        "$schema": DIALECT,
        "$ref": "#/$defs/subject",
        "$defs": {"subject": schema},
        "components": document.get("components", {}),
    }


def _validate_instance(
    document: JsonObject, schema: Any, instance: Any, label: str, errors: list[str]
) -> None:
    wrapper = _schema_wrapper(document, schema)
    try:
        validation_errors = list(OAS32Validator(wrapper).iter_errors(instance))
    except Exception as error:  # unresolved references have backend-specific types
        errors.append(f"{label} example validation failed: {error}")
        return
    for error in validation_errors:
        path = "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{label} example is invalid at {path or '$'}: {error.message}")


def _examples(media: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    if "example" in media:
        yield "example", {"value": media["example"]}
    examples = media.get("examples")
    if isinstance(examples, Mapping):
        for name, example in examples.items():
            if isinstance(example, Mapping):
                yield str(name), example


def _validate_media_examples(
    document: JsonObject,
    media_type: str,
    media: Mapping[str, Any],
    label: str,
    errors: list[str],
) -> None:
    schema = media.get("schema")
    item_schema = media.get("itemSchema")
    if schema is None and item_schema is None:
        errors.append(f"{label} {media_type} has no schema or itemSchema")
        return
    examples = list(_examples(media))
    if not examples:
        errors.append(f"{label} {media_type} has no example")
        return
    for name, raw_example in examples:
        try:
            example = dereference(document, raw_example)
        except ContractError as error:
            errors.append(f"{label} {name}: {error}")
            continue
        if not isinstance(example, Mapping):
            errors.append(f"{label} {name} is not an Example Object")
            continue
        example_label = f"{label} {name}"
        if item_schema is not None:
            value = example.get("value")
            if not isinstance(value, str):
                errors.append(f"{example_label} NDJSON value is not a string")
                continue
            lines = [line for line in value.splitlines() if line]
            if not lines:
                errors.append(f"{example_label} NDJSON value has no lines")
            for index, line in enumerate(lines, start=1):
                try:
                    item = json.loads(line, object_pairs_hook=_reject_json_duplicates)
                except (ContractError, json.JSONDecodeError) as error:
                    errors.append(f"{example_label} NDJSON line {index} is invalid JSON: {error}")
                    continue
                _validate_instance(
                    document, item_schema, item, f"{example_label} NDJSON line {index}", errors
                )
            continue
        value_key = "dataValue" if media_type == "application/x-www-form-urlencoded" else "value"
        if value_key not in example:
            errors.append(f"{example_label} has no {value_key}")
            continue
        if media_type == "application/x-www-form-urlencoded" and not isinstance(
            example.get("serializedValue"), str
        ):
            errors.append(f"{example_label} has no serializedValue")
        elif media_type == "application/x-www-form-urlencoded":
            _validate_form_example(example, example_label, errors)
        _validate_instance(document, schema, example[value_key], example_label, errors)


def _reject_json_duplicates(pairs: list[tuple[str, Any]]) -> JsonObject:
    value: JsonObject = {}
    for key, item in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON member {key!r}")
        value[key] = item
    return value


def _form_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _validate_form_example(
    example: Mapping[str, Any], label: str, errors: list[str]
) -> None:
    data = example.get("dataValue")
    serialized = example.get("serializedValue")
    if not isinstance(data, Mapping) or not isinstance(serialized, str):
        return
    try:
        pairs = urllib.parse.parse_qsl(
            serialized,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeError, ValueError) as error:
        errors.append(f"{label} serializedValue is invalid: {error}")
        return
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        errors.append(f"{label} serializedValue contains a repeated property")
        return
    decoded = {key: value for key, value in pairs}
    expected = {str(key): _form_scalar(value) for key, value in data.items()}
    if decoded != expected:
        errors.append(f"{label} serializedValue does not match dataValue")


def _resolved_media(
    document: JsonObject, container: Mapping[str, Any], label: str, errors: list[str]
) -> Mapping[str, Any]:
    content = container.get("content")
    if not isinstance(content, Mapping):
        errors.append(f"{label} has no content map")
        return {}
    for media_type, raw_media in content.items():
        try:
            media = dereference(document, raw_media)
        except ContractError as error:
            errors.append(f"{label} {media_type}: {error}")
            continue
        if not isinstance(media, Mapping):
            errors.append(f"{label} {media_type} is not a Media Type Object")
            continue
        _validate_media_examples(document, str(media_type), media, label, errors)
    return content


def _check_structure(document: JsonObject, errors: list[str]) -> None:
    if document.get("openapi") != "3.2.0":
        errors.append("openapi must equal 3.2.0")
    if document.get("jsonSchemaDialect") != DIALECT:
        errors.append(f"jsonSchemaDialect must equal {DIALECT}")
    info = document.get("info")
    if not isinstance(info, Mapping) or info.get("version") != "0.2.0":
        errors.append("info.version must equal 0.2.0")
    if set(document.get("paths", {})) != {"/v1/events", "/v1/streams", "/v1/sources/retire"}:
        errors.append("paths must contain exactly the three public route paths")
    if "security" in document:
        errors.append("security must not claim one authentication rule for every deployment")
    authentication = document.get("x-deployment-authentication")
    if authentication != {
        "configuration": "server.token",
        "empty": "No authentication is required.",
        "configured": "Every request requires the bearerAuth scheme before routing.",
    }:
        errors.append("x-deployment-authentication must describe server.token behavior")
    schemas = document.get("components", {}).get("schemas", {})
    if not RETAINED_SCHEMAS.issubset(schemas):
        errors.append("components.schemas omits a retained public schema")


def _check_references(document: JsonObject, errors: list[str]) -> None:
    for location, value in _walk(document):
        if isinstance(value, Mapping) and "$ref" in value:
            reference = value["$ref"]
            if not isinstance(reference, str):
                errors.append(f"{location}/$ref is not a string")
                continue
            try:
                resolve_local(document, reference)
            except ContractError as error:
                errors.append(f"{location}: {error}")


def _check_operations(document: JsonObject, errors: list[str]) -> None:
    actual = {(path, method): operation for path, method, operation in _operations(document)}
    if set(actual) != set(EXPECTED_OPERATIONS):
        errors.append("the document must define exactly the six public operations")
    operation_ids: list[str] = []
    for key, (operation_id, statuses, query_reference) in EXPECTED_OPERATIONS.items():
        operation = actual.get(key)
        if operation is None:
            continue
        if operation.get("operationId") != operation_id:
            errors.append(f"{key} operationId must equal {operation_id}")
        if isinstance(operation.get("operationId"), str):
            operation_ids.append(operation["operationId"])
        parameters = operation.get("parameters")
        if parameters != [{"$ref": query_reference}]:
            errors.append(f"{key} must use only {query_reference}")
        responses = operation.get("responses")
        if not isinstance(responses, Mapping):
            errors.append(f"{key} has no responses")
        elif set(responses) != statuses:
            errors.append(f"{key} response statuses must equal {sorted(statuses)}")
    if len(operation_ids) != len(set(operation_ids)):
        errors.append("operationId values must be unique")


def _check_query_parameters(document: JsonObject, errors: list[str]) -> None:
    expected = {
        "NoQuery": "#/components/schemas/NoQuery",
        "ReplayQuery": "#/components/schemas/ReplayQuery",
        "StreamsQuery": "#/components/schemas/StreamsQuery",
    }
    parameters = document.get("components", {}).get("parameters", {})
    for name, schema_reference in expected.items():
        parameter = parameters.get(name)
        if not isinstance(parameter, Mapping):
            errors.append(f"components.parameters.{name} is missing")
            continue
        if parameter.get("in") != "querystring":
            errors.append(f"components.parameters.{name} must use in: querystring")
        content = _resolved_media(document, parameter, f"query parameter {name}", errors)
        if set(content) != {"application/x-www-form-urlencoded"}:
            errors.append(f"query parameter {name} must use form media")
            continue
        media = dereference(document, content["application/x-www-form-urlencoded"])
        if media.get("schema") != {"$ref": schema_reference}:
            errors.append(f"query parameter {name} must use {schema_reference}")


def _check_requests(document: JsonObject, errors: list[str]) -> None:
    actual = {(path, method): operation for path, method, operation in _operations(document)}
    for key, operation in actual.items():
        request = operation.get("requestBody")
        if key not in REQUEST_SCHEMAS:
            if request is not None:
                errors.append(f"{key} must not define a request body")
            continue
        if not isinstance(request, Mapping) or request.get("required") is not True:
            errors.append(f"{key} must require a request body")
            continue
        content = _resolved_media(document, request, f"{key} request", errors)
        if set(content) != {"application/json"}:
            errors.append(f"{key} request must use application/json")
            continue
        media = dereference(document, content["application/json"])
        if media.get("schema") != {"$ref": REQUEST_SCHEMAS[key]}:
            errors.append(f"{key} request uses the wrong schema")


def _check_response_media(
    document: JsonObject,
    key: tuple[str, str],
    status: str,
    response: Mapping[str, Any],
    errors: list[str],
) -> None:
    label = f"{key} response {status}"
    if key[1] == "head":
        if "content" in response:
            errors.append(f"{label} must not define a response body")
        return
    content = _resolved_media(document, response, label, errors)
    expected_media = {"application/json"}
    if key == ("/v1/events", "get") and status == "200":
        expected_media.add("application/x-ndjson")
    if set(content) != expected_media:
        errors.append(f"{label} media types must equal {sorted(expected_media)}")
    if key == ("/v1/events", "get") and status == "200":
        finite = dereference(document, content.get("application/json", {}))
        follow = dereference(document, content.get("application/x-ndjson", {}))
        if finite.get("schema") != {"$ref": "#/components/schemas/ReplayResponse"}:
            errors.append("finite replay must use ReplayResponse")
        if follow.get("itemSchema") != {"$ref": "#/components/schemas/FollowRecord"}:
            errors.append("NDJSON follow must use FollowRecord as itemSchema")


def _check_responses(document: JsonObject, errors: list[str]) -> None:
    for path, method, operation in _operations(document):
        key = (path, method)
        responses = operation.get("responses")
        if not isinstance(responses, Mapping):
            continue
        for status, raw_response in responses.items():
            try:
                response = dereference(document, raw_response)
            except ContractError as error:
                errors.append(f"{key} response {status}: {error}")
                continue
            if not isinstance(response, Mapping):
                errors.append(f"{key} response {status} is not a Response Object")
                continue
            _check_response_media(document, key, str(status), response, errors)


def _check_errors_and_headers(document: JsonObject, errors: list[str]) -> None:
    error_code = document.get("components", {}).get("schemas", {}).get("ErrorCode", {})
    if set(error_code.get("enum", [])) != set(ERROR_STATUSES):
        errors.append("ErrorCode.enum does not match the stable error-code set")
    if error_code.get("x-http-status") != ERROR_STATUSES:
        errors.append("ErrorCode.x-http-status does not match the stable status map")

    for path, method, operation in _operations(document):
        responses = operation.get("responses", {})
        for status, raw_response in responses.items():
            response = dereference(document, raw_response)
            headers = response.get("headers", {}) if isinstance(response, Mapping) else {}
            if str(status) == "429" and "Retry-After" not in headers:
                errors.append(f"{(path, method)} response 429 must define Retry-After")
            if {"Cache-Control", "Connection"} & set(headers):
                errors.append(f"{(path, method)} response {status} declares follow-only headers")
            if method == "head" or str(status) == "200" or not isinstance(response, Mapping):
                continue
            content = response.get("content", {})
            media = dereference(document, content.get("application/json", {}))
            for name, raw_example in _examples(media):
                example = dereference(document, raw_example)
                value = example.get("value") if isinstance(example, Mapping) else None
                code = value.get("error") if isinstance(value, Mapping) else None
                if code not in ERROR_STATUSES:
                    errors.append(f"{(path, method)} response {status} example {name} lacks a stable error")
                elif ERROR_STATUSES[code] != int(status):
                    errors.append(
                        f"{(path, method)} response {status} example {name} uses {code}"
                    )
    replay = document.get("paths", {}).get("/v1/events", {}).get("get", {})
    if replay.get("x-follow-response-headers") != {
        "Cache-Control": "no-store",
        "Connection": "close",
    }:
        errors.append("replay must define the two follow-only response headers")


def _check_semantic_extensions(document: JsonObject, errors: list[str]) -> None:
    schemas = document.get("components", {}).get("schemas", {})
    replay_limit = schemas.get("ReplayQuery", {}).get("properties", {}).get("limit", {})
    if "maximum" in replay_limit or "default" in replay_limit:
        errors.append("replay limit must not publish a fixed default or maximum")
    if replay_limit.get("x-configured-maximum") != "replay.max_limit":
        errors.append("replay limit must identify replay.max_limit")
    if replay_limit.get("x-configured-default") != "replay.default_limit":
        errors.append("replay limit must identify replay.default_limit")
    for name in ("ReplayResponse", "FollowEvents"):
        events = schemas.get(name, {}).get("properties", {}).get("events", {})
        if "maxItems" in events:
            errors.append(f"{name}.events must not publish a fixed maximum")

    json_rules = schemas.get("SubmittedEvent", {}).get("x-json-input-rules", {})
    if set(json_rules) != {
        "duplicate-members",
        "numbers",
        "payload-container-depth",
        "occurred-at",
    } or json_rules.get("payload-container-depth") != 128:
        errors.append("SubmittedEvent must define the four strict JSON input rules")
    append_invariants = schemas.get("AppendBatch", {}).get("x-invariants")
    if not isinstance(append_invariants, list) or not any(
        "stream_precondition.stream" in str(item) for item in append_invariants
    ):
        errors.append("AppendBatch must define its stream-precondition invariant")
    replay_invariants = schemas.get("ReplayResponse", {}).get("x-invariants")
    if not isinstance(replay_invariants, list) or len(replay_invariants) < 5:
        errors.append("ReplayResponse must define cursor and frontier invariants")
    lineage_invariants = schemas.get("LineagePayload", {}).get("x-invariants")
    if not isinstance(lineage_invariants, list) or len(lineage_invariants) < 5:
        errors.append("LineagePayload must define successor-lineage invariants")

    error_schema = schemas.get("Error", {})
    conditional = error_schema.get("allOf")
    if not isinstance(conditional, list) or not conditional:
        errors.append("Error must require indexed details for invalid_events")


def _check_schemas(document: JsonObject, errors: list[str]) -> None:
    schemas = document.get("components", {}).get("schemas", {})
    for name, schema in schemas.items():
        wrapper = _schema_wrapper(document, schema)
        try:
            OAS32Validator.check_schema(wrapper)
        except Exception as error:  # validator exception types vary by backend
            errors.append(f"component schema {name} is invalid: {error}")


def validate_document(document: JsonObject) -> None:
    """Validate one parsed OpenAPI document or raise ContractError."""
    errors: list[str] = []
    try:
        validate_openapi(document)
    except Exception as error:  # the package exposes backend-specific exceptions
        errors.append(f"OpenAPI 3.2 validation failed: {error}")
    checks: tuple[Callable[[JsonObject, list[str]], None], ...] = (
        _check_structure,
        _check_references,
        _check_operations,
        _check_query_parameters,
        _check_requests,
        _check_responses,
        _check_errors_and_headers,
        _check_semantic_extensions,
        _check_schemas,
    )
    for check in checks:
        try:
            check(document, errors)
        except (ContractError, KeyError, TypeError, ValueError) as error:
            errors.append(f"{check.__name__} failed: {error}")
    if errors:
        raise ContractError("\n".join(f"- {error}" for error in errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", type=Path, default=Path("openapi.yaml"))
    arguments = parser.parse_args()
    try:
        document = load_document(arguments.document)
        validate_document(document)
    except ContractError as error:
        print(error)
        return 1
    print(f"validated {arguments.document}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

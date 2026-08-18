#!/usr/bin/env python3
"""Validate the version 1 Agent Record and Agent Operations contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parent / "v1"
SCHEMA_FILE = "agent-record-event-schemas.json"
EVENT_MANIFEST_FILE = "agent-record-event-manifest.json"
RELATIONS_FILE = "agent-operations-relations.json"
QUERY_MATRIX_FILE = "agent-operations-query-matrix.json"
SAVED_QUERIES_FILE = "agent-operations-saved-queries.json"
PACK_FILE = "agent-operations-pack.json"

NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
RELATION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}\.[a-z][a-z0-9_]{0,62}$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
FIELD_TYPES = {"bool", "i64", "u64", "f64", "utf8", "uuid", "timestamp_us_utc", "json"}
FILTER_OPERATORS = {
    "and",
    "or",
    "not",
    "eq",
    "not_eq",
    "in",
    "not_in",
    "lt",
    "lte",
    "gt",
    "gte",
    "contains",
    "contains_any",
    "is_null",
    "is_not_null",
}

EVENT_GROUPS = (
    ("agent_runtime", "sessions", "session_id", ("session.started", "session.completed")),
    ("agent_runtime", "runs", "run_id", ("run.started", "run.waiting", "run.resumed", "run.completed", "run.failed")),
    ("agent_runtime", "messages", "session_id", ("input.received", "output.created")),
    ("agent_runtime", "context", "run_id", ("context.loaded",)),
    ("agent_runtime", "model_calls", "model_call_id", ("model.requested", "model.responded", "model.failed")),
    ("agent_runtime", "tool_calls", "tool_call_id", ("tool.requested", "tool.completed", "tool.failed")),
    ("agent_runtime", "controls", "control_id", ("control.requested", "control.applied", "control.rejected")),
    ("call_gateway", "calls", "call_id", ("call.requested", "call.authorized", "call.refused", "call.cancel_requested")),
    ("action_runtime", "policies", "call_id", ("policy.allowed", "policy.denied", "policy.approval_required")),
    ("action_runtime", "approvals", "call_id", ("approval.requested", "approval.claimed", "approval.released", "approval.approved", "approval.denied", "approval.edited", "approval.expired")),
    ("action_runtime", "actions", "call_id", ("action.proposed", "action.superseded", "action.resolved")),
    ("action_runtime", "dispatch", "call_id", ("call.ready", "dispatch.claimed", "retry.requested", "retry.scheduled", "reconciliation.requested")),
    ("provider_execution", "attempts", "call_id", ("attempt.started", "attempt.transmission_started", "attempt.finished")),
    ("provider_execution", "api_calls", "call_id", ("api.requested", "api.responded", "api.transport_failed")),
    ("provider_execution", "observations", "call_id", ("provider.observed", "provider.observation_failed")),
    ("provider_execution", "resolutions", "call_id", ("call.resolution_reported", "call.confirmation_reported", "call.reconciled", "call.reconciliation_failed")),
    ("memory_extractor", "memory", "subject_key", ("memory.proposed", "memory.accepted", "memory.corrected", "memory.superseded", "memory.retracted")),
    ("evaluation", "evaluations", "evaluation_id", ("evaluation.scored", "evaluation.flagged")),
    ("projection_worker", "projections", "projection_name", ("projection.rebuild_started", "projection.rebuild_published", "projection.rebuild_failed")),
)

PRIMARY_KEYS = {
    "agents.runs_current": ("run_id",),
    "agents.session_timeline": ("session_id", "sequence"),
    "agents.tool_calls_current": ("tool_call_id",),
    "calls.calls_current": ("call_id",),
    "actions.actions_pending": ("call_id",),
    "providers.state_observed": ("demo_session_id", "resource_type", "resource_id"),
    "providers.state_optimistic": ("demo_session_id", "resource_type", "resource_id"),
    "providers.state_effective": ("demo_session_id", "resource_type", "resource_id"),
    "memory.memory_current": ("scope_id", "subject", "key"),
    "memory.memory_history": ("scope_id", "subject", "key", "memory_event_id"),
    "memory.memory_evidence": ("memory_event_id", "evidence_event_id"),
    "api.health_minute": ("provider", "operation", "minute"),
    "evaluations.current": ("run_id", "evaluator"),
    "usage.workspace_daily": ("workspace_id", "day"),
    "usage.usage_by_operation": ("workspace_id", "day", "provider", "operation"),
    "projections.state": ("projection_name",),
}

PROVIDER_INDEXES = {
    "by_demo_session": ("posting", ("demo_session_id",)),
    "by_resource_type": ("posting", ("resource_type",)),
    "by_updated": ("ordered", ("updated_at", "resource_id", "demo_session_id", "resource_type")),
}
INDEXES = {
    "agents.runs_current": {
        "by_demo_session": ("posting", ("demo_session_id",)),
        "by_workspace": ("posting", ("workspace_id",)),
        "by_status": ("posting", ("status",)),
        "by_started": ("ordered", ("started_at", "run_id")),
        "by_completed": ("ordered", ("completed_at", "run_id")),
    },
    "agents.session_timeline": {
        "by_tool_call_sequence": ("ordered", ("tool_call_id", "sequence", "session_id")),
        "by_call_sequence": ("ordered", ("call_id", "sequence", "session_id")),
    },
    "agents.tool_calls_current": {
        "by_run": ("posting", ("run_id",)),
        "by_initial_resolution": ("posting", ("initial_resolution",)),
        "by_final_resolution": ("posting", ("final_resolution",)),
        "by_started": ("ordered", ("started_at", "tool_call_id")),
    },
    "calls.calls_current": {
        "by_demo_session": ("posting", ("demo_session_id",)),
        "by_workspace": ("posting", ("workspace_id",)),
        "by_provider": ("posting", ("provider",)),
        "by_operation": ("posting", ("operation",)),
        "by_mode": ("posting", ("mode",)),
        "by_policy_result": ("posting", ("policy_result",)),
        "by_state": ("posting", ("state",)),
        "by_resolution": ("posting", ("resolution",)),
        "by_run": ("posting", ("run_id",)),
        "by_requested": ("ordered", ("requested_at", "call_id")),
    },
    "actions.actions_pending": {
        "by_demo_session": ("posting", ("demo_session_id",)),
        "by_state": ("posting", ("state",)),
        "by_requested": ("ordered", ("requested_at", "call_id")),
    },
    "providers.state_observed": PROVIDER_INDEXES,
    "providers.state_optimistic": PROVIDER_INDEXES,
    "providers.state_effective": PROVIDER_INDEXES,
    "memory.memory_current": {
        "by_scope": ("posting", ("scope_id",)),
        "by_subject": ("posting", ("subject",)),
        "by_key": ("posting", ("key",)),
        "by_evidence_class": ("posting", ("evidence_classes",)),
        "by_updated": ("ordered", ("updated_at", "scope_id", "subject", "key")),
    },
    "memory.memory_history": {
        "by_memory_sequence": ("ordered", ("scope_id", "subject", "key", "sequence", "memory_event_id")),
    },
    "memory.memory_evidence": {},
    "api.health_minute": {
        "by_provider": ("posting", ("provider",)),
        "by_operation": ("posting", ("operation",)),
        "by_minute": ("ordered", ("minute", "provider", "operation")),
    },
    "evaluations.current": {},
    "usage.workspace_daily": {},
    "usage.usage_by_operation": {
        "by_provider": ("posting", ("provider",)),
        "by_operation": ("posting", ("operation",)),
    },
    "projections.state": {"by_status": ("posting", ("status",))},
}

LEGACY_ALIASES = {
    "actions_pending": "actions.actions_pending",
    "api_health_minute": "api.health_minute",
    "calls_current": "calls.calls_current",
    "events_index": "groundhog.events",
    "evaluations_current": "evaluations.current",
    "memory_current": "memory.memory_current",
    "memory_evidence": "memory.memory_evidence",
    "memory_history": "memory.memory_history",
    "projection_state": "projections.state",
    "provider_state_effective": "providers.state_effective",
    "provider_state_observed": "providers.state_observed",
    "provider_state_optimistic": "providers.state_optimistic",
    "runs_current": "agents.runs_current",
    "session_timeline": "agents.session_timeline",
    "tool_calls_current": "agents.tool_calls_current",
    "usage_by_operation": "usage.usage_by_operation",
    "workspace_usage_daily": "usage.workspace_daily",
}

QUERY_SHAPES = {
    "Q01": (("groundhog.events",), ("source", "stream", "record_key", "kind", "observed_at"), (("event_id", "desc"),), ("by_source", "by_stream", "by_record_key", "by_kind", "by_observed_at", "primary_key")),
    "Q02": (("groundhog.events",), ("event_id",), (("event_id", "asc"),), ("primary_key",)),
    "Q03": (("agents.runs_current",), ("demo_session_id", "workspace_id", "status"), (("started_at", "desc"),), ("by_demo_session", "by_workspace", "by_status", "by_started")),
    "Q04": (("agents.runs_current",), ("run_id",), (("run_id", "asc"),), ("primary_key",)),
    "Q05": (("agents.session_timeline",), ("session_id",), (("sequence", "asc"),), ("primary_key",)),
    "Q06": (("agents.session_timeline",), ("tool_call_id",), (("sequence", "asc"),), ("by_tool_call_sequence",)),
    "Q07": (("agents.session_timeline",), ("call_id",), (("sequence", "asc"),), ("by_call_sequence",)),
    "Q08": (("agents.tool_calls_current",), ("tool_call_id",), (("tool_call_id", "asc"),), ("primary_key",)),
    "Q09": (("agents.tool_calls_current",), ("run_id", "initial_resolution", "final_resolution"), (("started_at", "asc"),), ("by_run", "by_initial_resolution", "by_final_resolution", "by_started")),
    "Q10": (("calls.calls_current",), ("demo_session_id", "workspace_id", "provider", "operation", "mode", "policy_result", "state", "resolution", "run_id"), (("requested_at", "desc"),), ("by_demo_session", "by_workspace", "by_provider", "by_operation", "by_mode", "by_policy_result", "by_state", "by_resolution", "by_run", "by_requested")),
    "Q11": (("calls.calls_current",), ("call_id",), (("call_id", "asc"),), ("primary_key",)),
    "Q12": (("actions.actions_pending",), ("demo_session_id", "state"), (("requested_at", "asc"),), ("by_demo_session", "by_state", "by_requested")),
    "Q13": (("providers.state_observed", "providers.state_optimistic", "providers.state_effective"), ("demo_session_id", "resource_type", "resource_id"), (("demo_session_id", "asc"), ("resource_type", "asc"), ("resource_id", "asc")), ("primary_key",)),
    "Q14": (("providers.state_effective",), ("demo_session_id", "resource_type"), (("updated_at", "desc"),), ("by_demo_session", "by_resource_type", "by_updated")),
    "Q15": (("memory.memory_current",), ("scope_id", "subject", "key"), (("updated_at", "desc"),), ("by_scope", "by_subject", "by_key", "by_updated")),
    "Q16": (("memory.memory_current",), ("scope_id", "evidence_classes"), (("updated_at", "desc"),), ("by_scope", "by_evidence_class", "by_updated")),
    "Q17": (("memory.memory_history",), ("scope_id", "subject", "key"), (("sequence", "asc"),), ("by_memory_sequence",)),
    "Q18": (("memory.memory_evidence",), ("memory_event_id",), (("evidence_event_id", "asc"),), ("primary_key",)),
    "Q19": (("api.health_minute",), ("provider", "operation", "minute"), (("minute", "asc"),), ("by_provider", "by_operation", "by_minute")),
    "Q20": (("evaluations.current",), ("run_id", "evaluator"), (("evaluator", "asc"),), ("primary_key",)),
    "Q21": (("usage.workspace_daily",), ("workspace_id", "day"), (("day", "asc"),), ("primary_key",)),
    "Q22": (("usage.usage_by_operation",), ("workspace_id", "day", "provider", "operation"), (("day", "asc"),), ("primary_key", "by_provider", "by_operation")),
    "Q23": (("projections.state",), ("status",), (("projection_name", "asc"),), ("by_status", "primary_key")),
}

SAVED_QUERY_MATRIX_IDS = {
    "provider_latency_and_failure_rate_by_operation": ("Q19",),
    "runs_waiting_for_human_approval": ("Q03", "Q12"),
    "tool_calls_with_initially_unknown_outcome": ("Q09",),
    "current_memory_from_failed_or_retried_calls": ("Q16",),
    "all_events_and_views_for_tool_call": ("Q06", "Q08", "Q11", "Q02"),
    "run_outcomes_before_and_after_retry": ("Q04", "Q05", "Q09", "Q20"),
    "daily_usage_by_workspace": ("Q21", "Q22"),
    "policy_denied_calls_and_requesting_runs": ("Q10", "Q04"),
}

EVENT_FIELDS = {
    "event_id", "source", "stream", "record_key", "kind", "observed_at",
    "occurred_at", "batch_id", "payload", "content_hash", "event_hash",
}
EVENT_INDEXES = {"by_source", "by_stream", "by_record_key", "by_kind", "by_observed_at", "primary_key"}


class ContractError(ValueError):
    """One contract validation rule failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON member {key!r}")
        value[key] = item
    return value


def load_json(name: str) -> dict[str, Any]:
    path = CONTRACTS / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot load {path}: {error}") from error
    require(isinstance(value, dict), f"{name} must contain one JSON object")
    return value


def file_hash(name: str) -> str:
    return "sha256:" + hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest()


def resolve_pointer(document: Any, pointer: str) -> Any:
    require(pointer.startswith("#/"), f"reference is not a local JSON Pointer: {pointer}")
    current = document
    for raw in pointer[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        require(isinstance(current, Mapping) and token in current, f"unresolved reference {pointer}")
        current = current[token]
    return current


def object_contract(root: Mapping[str, Any], schema: Any) -> tuple[set[str], dict[str, Any]]:
    if isinstance(schema, Mapping) and isinstance(schema.get("$ref"), str):
        return object_contract(root, resolve_pointer(root, schema["$ref"]))
    require(isinstance(schema, Mapping), "event payload schema must be an object")
    required = set(schema.get("required", []))
    properties = dict(schema.get("properties", {}))
    for part in schema.get("allOf", []):
        part_required, part_properties = object_contract(root, part)
        required.update(part_required)
        properties.update(part_properties)
    return required, properties


def sample_value(root: Mapping[str, Any], schema: Any) -> Any:
    if schema is True:
        return None
    require(isinstance(schema, Mapping), "property schema must be an object or true")
    if isinstance(schema.get("$ref"), str):
        return sample_value(root, resolve_pointer(root, schema["$ref"]))
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "string":
        pattern = schema.get("pattern", "")
        if "sha256:" in pattern:
            return "sha256:" + "0" * 64
        if "7[0-9a-f]" in pattern:
            return "019c0000-0000-7000-8000-000000000001"
        if "T[0-9]" in pattern:
            return "2026-08-12T00:00:00.000000Z"
        return "x"
    if kind == "integer":
        return int(schema.get("minimum", 0))
    if kind == "number":
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        required, properties = object_contract(root, schema)
        return {name: sample_value(root, properties[name]) for name in required}
    return None


def validate_event_contracts(schema_set: dict[str, Any], manifest: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema_set)
    expected: dict[str, tuple[str, str, str, str]] = {}
    for source, schema_name, record_key, kinds in EVENT_GROUPS:
        stream = "deltas" if schema_name == "memory" else {
            "evaluations": "results", "projections": "operations"
        }.get(schema_name, schema_name)
        for kind in kinds:
            expected[kind] = (source, stream, record_key, schema_name)
    require(len(expected) == 63, "the validator event taxonomy must contain 63 kinds")

    events = manifest.get("events")
    require(isinstance(events, list), "event manifest events must be an array")
    actual = {event.get("kind"): event for event in events if isinstance(event, Mapping)}
    require(len(events) == 63 and len(actual) == 63, "event manifest must contain 63 unique kinds")
    require(set(actual) == set(expected), "event manifest kinds do not match the demo taxonomy")
    schema_hash = file_hash(SCHEMA_FILE)
    require(manifest.get("schema_set") == {"path": SCHEMA_FILE, "hash": schema_hash}, "event manifest schema-set hash is stale")
    require(manifest.get("schema_hash_scope") == "complete_schema_document", "event manifest uses an unknown schema hash scope")

    for kind, event in actual.items():
        source, stream, record_key, schema_name = expected[str(kind)]
        require(event.get("source") == source, f"{kind} has the wrong source")
        require(event.get("stream") == stream, f"{kind} has the wrong stream")
        require(event.get("record_key_field") == record_key, f"{kind} has the wrong record-key field")
        schema_uri = f"{SCHEMA_FILE}#/$defs/{schema_name}"
        require(event.get("schema_uri") == schema_uri, f"{kind} has the wrong schema URI")
        require(event.get("schema_hash") == schema_hash, f"{kind} has a stale schema hash")
        require(event.get("schema_version") == 1, f"{kind} has the wrong schema version")
        target = resolve_pointer(schema_set, f"#/$defs/{schema_name}")
        require(target.get("unevaluatedProperties") is False, f"{schema_name} is not closed")
        required, properties = object_contract(schema_set, target)
        require(set(event.get("required_fields", [])) == required, f"{kind} required fields do not match its schema")
        if record_key != "subject_key":
            require(record_key in properties, f"{kind} record-key field is absent from its schema")
        instance = {name: sample_value(schema_set, properties[name]) for name in required}
        wrapper = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{schema_name}",
            "$defs": schema_set["$defs"],
        }
        validator = Draft202012Validator(wrapper)
        errors = list(validator.iter_errors(instance))
        require(not errors, f"{kind} minimal payload fails JSON Schema: {errors[0].message if errors else ''}")
        instance["unexpected"] = True
        require(bool(list(validator.iter_errors(instance))), f"{kind} schema accepts an unknown member")


def relation_maps(relations_document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, set[str]]]:
    relations = relations_document.get("relations")
    require(isinstance(relations, list), "relations must be an array")
    relation_by_name = {item.get("relation"): item for item in relations if isinstance(item, Mapping)}
    require(len(relations) == 16 and len(relation_by_name) == 16, "relation contract must contain 16 unique relations")
    require(set(relation_by_name) == set(PRIMARY_KEYS), "canonical relation set does not match P0")
    fields_by_relation: dict[str, set[str]] = {}
    indexes_by_relation: dict[str, set[str]] = {}

    for name, relation in relation_by_name.items():
        require(isinstance(name, str) and RELATION_NAME.fullmatch(name) is not None, f"invalid relation name {name!r}")
        require(tuple(relation.get("primary_key", [])) == PRIMARY_KEYS[name], f"{name} has the wrong primary key")
        fields = relation.get("fields")
        require(isinstance(fields, list) and fields, f"{name} must declare fields")
        fields_by_name = {field.get("name"): field for field in fields if isinstance(field, Mapping)}
        require(len(fields_by_name) == len(fields), f"{name} has duplicate field names")
        for field_name, field in fields_by_name.items():
            require(isinstance(field_name, str) and NAME.fullmatch(field_name) is not None, f"{name} has invalid field {field_name!r}")
            field_type = field.get("type")
            require(field_type == "list" or field_type in FIELD_TYPES, f"{name}.{field_name} has an invalid type")
            require(isinstance(field.get("nullable"), bool), f"{name}.{field_name} must declare nullability")
            if field_type == "list":
                require(field.get("element_type") in FIELD_TYPES - {"json"}, f"{name}.{field_name} has an invalid list element type")
                require(isinstance(field.get("element_nullable"), bool), f"{name}.{field_name} must declare element nullability")
        for key in PRIMARY_KEYS[name]:
            require(key in fields_by_name, f"{name} primary-key field {key} is missing")
            require(fields_by_name[key].get("nullable") is False, f"{name} primary-key field {key} is nullable")

        indexes = relation.get("indexes")
        require(isinstance(indexes, list), f"{name} indexes must be an array")
        actual_indexes = {
            index.get("name"): (index.get("kind"), tuple(index.get("fields", [])))
            for index in indexes if isinstance(index, Mapping)
        }
        require(len(actual_indexes) == len(indexes), f"{name} has duplicate index names")
        require(actual_indexes == INDEXES[name], f"{name} indexes do not match the P0 query matrix")
        for index_name, (kind, index_fields) in actual_indexes.items():
            require(isinstance(index_name, str) and NAME.fullmatch(index_name) is not None, f"{name} has an invalid index name")
            require(kind in {"posting", "ordered"}, f"{name}.{index_name} has an invalid index kind")
            require(bool(index_fields) and set(index_fields) <= set(fields_by_name), f"{name}.{index_name} references an unknown field")
            require(kind != "posting" or len(index_fields) == 1, f"{name}.{index_name} posting index must cover one field")
            if kind == "ordered":
                for field_name in index_fields:
                    require(fields_by_name[field_name].get("type") not in {"json", "list"}, f"{name}.{index_name} orders an unsupported field type")
        fields_by_relation[name] = set(fields_by_name)
        indexes_by_relation[name] = set(actual_indexes) | {"primary_key"}
    return relation_by_name, fields_by_relation, indexes_by_relation


def validate_query_matrix(matrix: dict[str, Any], fields: dict[str, set[str]], indexes: dict[str, set[str]]) -> dict[str, Any]:
    queries = matrix.get("queries")
    require(isinstance(queries, list), "query matrix queries must be an array")
    by_id = {query.get("id"): query for query in queries if isinstance(query, Mapping)}
    require(len(queries) == 23 and len(by_id) == 23, "query matrix must contain Q01 through Q23 once")
    require(set(by_id) == set(QUERY_SHAPES), "query matrix IDs do not match Q01 through Q23")

    for query_id, query in by_id.items():
        expected_relations, expected_filters, expected_order, expected_access = QUERY_SHAPES[str(query_id)]
        actual_relations = tuple(query.get("relations", [query.get("relation")]))
        require(actual_relations == expected_relations, f"{query_id} uses the wrong relation set")
        actual_filters = tuple(item.get("field") for item in query.get("filters", []))
        require(actual_filters == expected_filters, f"{query_id} filter fields do not match the P0 matrix")
        actual_order = tuple((item.get("field"), item.get("direction")) for item in query.get("order_by", []))
        require(actual_order == expected_order, f"{query_id} ordering does not match the P0 matrix")
        require(tuple(query.get("access_paths", [])) == expected_access, f"{query_id} access paths do not match the P0 matrix")
        for item in query.get("filters", []):
            require(set(item.get("operators", [])) <= FILTER_OPERATORS, f"{query_id} declares an unknown filter operator")
        for relation in actual_relations:
            relation_fields = EVENT_FIELDS if relation == "groundhog.events" else fields[relation]
            relation_indexes = EVENT_INDEXES if relation == "groundhog.events" else indexes[relation]
            require(set(expected_filters) <= relation_fields, f"{query_id} references a missing filter field in {relation}")
            require({field for field, _direction in expected_order} <= relation_fields, f"{query_id} references a missing order field in {relation}")
            require(set(expected_access) <= relation_indexes, f"{query_id} references a missing access path in {relation}")
    return by_id


def iter_references(value: Any) -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        if set(value) == {"$param"}:
            yield "param", value
            return
        if set(value) == {"$result"}:
            yield "result", value["$result"]
            return
        if set(value) == {"$result_union"}:
            references = value["$result_union"]
            require(isinstance(references, list) and references, "result union must contain references")
            for reference in references:
                require(isinstance(reference, Mapping), "result union reference must be an object")
                yield "result", reference
            return
        for child in value.values():
            yield from iter_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_references(child)


def validate_filter(filter_value: Mapping[str, Any], relation_fields: set[str], label: str) -> None:
    operator = filter_value.get("op")
    require(operator in FILTER_OPERATORS, f"{label} uses an unknown filter operator")
    if operator in {"and", "or"}:
        args = filter_value.get("args")
        require(isinstance(args, list) and len(args) >= 2, f"{label} boolean filter needs at least two children")
        for child in args:
            require(isinstance(child, Mapping), f"{label} filter child must be an object")
            validate_filter(child, relation_fields, label)
    elif operator == "not":
        child = filter_value.get("arg")
        require(isinstance(child, Mapping), f"{label} not filter needs one child")
        validate_filter(child, relation_fields, label)
    else:
        require(filter_value.get("field") in relation_fields, f"{label} filter references an unknown field")


def request_queries(request: Mapping[str, Any], fields: dict[str, set[str]], label: str) -> dict[str, set[str]]:
    require(request.get("v") == 1, f"{label} request version must equal 1")
    has_query = "query" in request
    has_queries = "queries" in request
    require(has_query != has_queries, f"{label} must contain query or queries")
    raw_queries = [("query", request.get("query"))] if has_query else [
        (item.get("name"), item.get("query")) for item in request.get("queries", [])
    ]
    require(1 <= len(raw_queries) <= 16, f"{label} has an invalid subquery count")
    outputs: dict[str, set[str]] = {}
    for result_name, query in raw_queries:
        require(isinstance(result_name, str) and NAME.fullmatch(result_name) is not None, f"{label} has an invalid result name")
        require(result_name not in outputs, f"{label} has a duplicate result name")
        require(isinstance(query, Mapping), f"{label}.{result_name} query must be an object")
        relation = query.get("relation")
        relation_fields = EVENT_FIELDS if relation == "groundhog.events" else fields.get(str(relation))
        require(relation_fields is not None, f"{label}.{result_name} uses an unknown relation")
        select = query.get("select")
        require(isinstance(select, list) and bool(select), f"{label}.{result_name} must select fields")
        require(len(select) == len(set(select)) and set(select) <= relation_fields, f"{label}.{result_name} selects an unknown or duplicate field")
        if "filter" in query:
            require(isinstance(query["filter"], Mapping), f"{label}.{result_name} filter must be an object")
            validate_filter(query["filter"], relation_fields, f"{label}.{result_name}")
        for order in query.get("order_by", []):
            require(order.get("field") in relation_fields, f"{label}.{result_name} orders by an unknown field")
            require(order.get("direction") in {"asc", "desc"}, f"{label}.{result_name} has an invalid direction")
        require(isinstance(query.get("limit", 100), int) and query.get("limit", 100) > 0, f"{label}.{result_name} has an invalid limit")
        outputs[result_name] = set(select)
    return outputs


def validate_result_reference(reference: Mapping[str, Any], prior_outputs: dict[str, dict[str, set[str]]], label: str) -> None:
    require(set(reference) == {"step", "result", "field"}, f"{label} result reference must name step, result, and field")
    step = reference.get("step")
    result = reference.get("result")
    field = reference.get("field")
    require(step in prior_outputs, f"{label} references an unknown or later step")
    require(result in prior_outputs[step], f"{label} references an unknown result")
    require(field in prior_outputs[step][result], f"{label} references an unselected field")


def validate_saved_queries(saved: dict[str, Any], fields: dict[str, set[str]], matrix: dict[str, Any]) -> dict[str, Any]:
    encoding = saved.get("template_encoding", {})
    require(encoding.get("prior_result_reference") == {"$result": {"step": "step_id", "result": "result_name", "field": "column_name"}}, "saved-query result references are ambiguous")
    require(encoding.get("prior_result_union") == {"$result_union": [{"step": "step_id", "result": "result_name", "field": "column_name"}]}, "saved-query result-union encoding is missing")
    queries = saved.get("saved_queries")
    require(isinstance(queries, list), "saved queries must be an array")
    by_id = {query.get("id"): query for query in queries if isinstance(query, Mapping)}
    require(len(queries) == 8 and len(by_id) == 8, "saved-query contract must contain eight unique queries")
    require(set(by_id) == set(SAVED_QUERY_MATRIX_IDS), "saved-query IDs do not match the P0 gallery")

    for saved_id, query in by_id.items():
        parameters = query.get("parameters", [])
        parameter_names = [parameter.get("name") for parameter in parameters]
        require(len(parameter_names) == len(set(parameter_names)), f"{saved_id} has duplicate parameters")
        workflows = query.get("workflow")
        require(isinstance(workflows, list) and workflows, f"{saved_id} must contain workflow steps")
        flattened_ids = tuple(matrix_id for step in workflows for matrix_id in step.get("query_matrix_ids", []))
        require(flattened_ids == SAVED_QUERY_MATRIX_IDS[saved_id], f"{saved_id} uses the wrong query-matrix IDs")
        prior_outputs: dict[str, dict[str, set[str]]] = {}
        for step in workflows:
            step_id = step.get("id")
            require(isinstance(step_id, str) and NAME.fullmatch(step_id) is not None, f"{saved_id} has an invalid step ID")
            require(step_id not in prior_outputs, f"{saved_id} has a duplicate step ID")
            for dependency in step.get("depends_on", []):
                require(dependency in prior_outputs, f"{saved_id}.{step_id} depends on an unknown or later step")
            repeat = step.get("repeat_for_each_distinct")
            if repeat is not None:
                require(isinstance(repeat, Mapping), f"{saved_id}.{step_id} repeat rule must be an object")
                validate_result_reference({key: repeat[key] for key in ("step", "result", "field") if key in repeat}, prior_outputs, f"{saved_id}.{step_id} repeat rule")
                require(isinstance(repeat.get("maximum"), int) and repeat["maximum"] > 0, f"{saved_id}.{step_id} repeat maximum is invalid")
            request = step.get("request_template")
            require(isinstance(request, Mapping), f"{saved_id}.{step_id} request template must be an object")
            for reference_kind, reference in iter_references(request):
                if reference_kind == "param":
                    require(reference.get("$param") in parameter_names, f"{saved_id}.{step_id} references an unknown parameter")
                else:
                    validate_result_reference(reference, prior_outputs, f"{saved_id}.{step_id}")
            outputs = request_queries(request, fields, f"{saved_id}.{step_id}")
            step_relations = {
                request["query"]["relation"]
            } if "query" in request else {
                item["query"]["relation"] for item in request["queries"]
            }
            matrix_relations = {
                relation
                for matrix_id in step.get("query_matrix_ids", [])
                for relation in QUERY_SHAPES[matrix_id][0]
            }
            require(step_relations <= matrix_relations, f"{saved_id}.{step_id} request does not match its query-matrix IDs")
            prior_outputs[step_id] = outputs
    return by_id


def validate_pack(pack: dict[str, Any], manifest: dict[str, Any], relations: dict[str, Any], matrix: dict[str, Any], saved: dict[str, Any]) -> None:
    require(pack.get("manifest_version") == 1 and pack.get("version") == 1, "pack version must equal 1")
    require(pack.get("event_schema_manifest") == {"path": EVENT_MANIFEST_FILE, "hash": file_hash(EVENT_MANIFEST_FILE)}, "pack event-manifest hash is stale")
    expected_artifacts = {
        "event_schemas": SCHEMA_FILE,
        "relations": RELATIONS_FILE,
        "query_matrix": QUERY_MATRIX_FILE,
        "saved_queries": SAVED_QUERIES_FILE,
    }
    actual_artifacts = {
        item.get("role"): (item.get("path"), item.get("hash"))
        for item in pack.get("artifacts", []) if isinstance(item, Mapping)
    }
    require(set(actual_artifacts) == set(expected_artifacts), "pack artifact roles are incomplete")
    for role, name in expected_artifacts.items():
        require(actual_artifacts[role] == (name, file_hash(name)), f"pack {role} hash is stale")
    require(set(pack.get("relations", [])) == set(relations), "pack relation list is stale")
    require(pack.get("built_in_sources") == ["groundhog.events"], "pack built-in source list is wrong")
    require(tuple(pack.get("query_matrix_ids", [])) == tuple(QUERY_SHAPES), "pack query-matrix ID list is stale")
    require(tuple(pack.get("saved_query_ids", [])) == tuple(SAVED_QUERY_MATRIX_IDS), "pack saved-query ID list is stale")
    require(pack.get("legacy_relation_aliases") == LEGACY_ALIASES, "pack legacy relation aliases are incomplete")
    require(manifest.get("schema_set", {}).get("hash") == file_hash(SCHEMA_FILE), "event manifest does not pin the schema file")
    require(set(matrix) == set(QUERY_SHAPES), "validated query matrix is incomplete")
    require(set(saved) == set(SAVED_QUERY_MATRIX_IDS), "validated saved-query set is incomplete")


def main() -> int:
    schema_set = load_json(SCHEMA_FILE)
    manifest = load_json(EVENT_MANIFEST_FILE)
    relations_document = load_json(RELATIONS_FILE)
    matrix_document = load_json(QUERY_MATRIX_FILE)
    saved_document = load_json(SAVED_QUERIES_FILE)
    pack = load_json(PACK_FILE)

    validate_event_contracts(schema_set, manifest)
    relations, fields, indexes = relation_maps(relations_document)
    matrix = validate_query_matrix(matrix_document, fields, indexes)
    saved = validate_saved_queries(saved_document, fields, matrix)
    validate_pack(pack, manifest, relations, matrix, saved)
    print("validated 63 event kinds, 16 relations, 23 query paths, and 8 saved queries")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        print(error)
        raise SystemExit(1) from error

"""A bounded linearizability search for recorded operations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
from typing import Iterable
from urllib.parse import urlsplit

from .history import History, OperationRecord, ResponseRecord, canonical_json
from .model import ModelViolation, SequentialModel


class CheckStatus(str, Enum):
    LINEARIZABLE = "linearizable"
    NONLINEARIZABLE = "nonlinearizable"
    INCONCLUSIVE = "inconclusive"
    BOUND_EXCEEDED = "bound_exceeded"


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    explored_states: int
    linearization: tuple[str, ...] = ()
    reason: str | None = None


class _BoundExceeded(Exception):
    pass


def check_history(
    history: History | Iterable[OperationRecord],
    *,
    max_states: int = 100_000,
    initial_model: SequentialModel | None = None,
) -> CheckResult:
    """Search legal serial orders that preserve completed-before-started order."""

    if max_states < 1:
        raise ValueError("max_states must be positive")
    operations = tuple(history.operations if isinstance(history, History) else history)
    operation_ids = [operation.operation_id for operation in operations]
    if len(set(operation_ids)) != len(operation_ids):
        raise ValueError("operation IDs must be unique")
    unresolved_indices = frozenset(
        index for index, operation in enumerate(operations) if operation.is_inconclusive
    )
    predecessors = _real_time_predecessors(operations)
    explored = 0

    def search(
        model: SequentialModel,
        completed: frozenset[int],
        order: tuple[str, ...],
        resolved_unknowns: frozenset[int],
    ) -> tuple[tuple[str, ...], bool] | None:
        nonlocal explored
        explored += 1
        if explored > max_states:
            raise _BoundExceeded
        if len(completed) == len(operations):
            return order, resolved_unknowns == unresolved_indices
        available = [
            index
            for index in range(len(operations))
            if index not in completed and predecessors[index].issubset(completed)
        ]
        inconclusive = None
        for index in available:
            operation = operations[index]
            candidates = _unknown_candidates(operation, operations)
            for resolved, resolved_operation in candidates:
                candidate = model.clone()
                if resolved_operation is not None:
                    try:
                        candidate.apply(resolved_operation)
                    except ModelViolation:
                        continue
                result = search(
                    candidate,
                    completed | {index},
                    order + (operation.operation_id,),
                    resolved_unknowns
                    | ({index} if resolved and index in unresolved_indices else set()),
                )
                if result is not None and result[1]:
                    return result
                if result is not None and inconclusive is None:
                    inconclusive = result
        return inconclusive

    try:
        result = search(
            initial_model or SequentialModel(), frozenset(), (), frozenset()
        )
    except _BoundExceeded:
        return CheckResult(
            CheckStatus.BOUND_EXCEEDED,
            explored,
            reason=f"search exceeded {max_states} modeled states",
        )
    if result is None:
        return CheckResult(
            CheckStatus.NONLINEARIZABLE,
            explored,
            reason="no legal sequential explanation preserves real-time order",
        )
    linearization, resolved = result
    if not resolved:
        identifiers = ", ".join(
            operations[index].operation_id for index in sorted(unresolved_indices)
        )
        return CheckResult(
            CheckStatus.INCONCLUSIVE,
            explored,
            linearization,
            reason=f"unresolved transport outcomes: {identifiers}",
        )
    return CheckResult(CheckStatus.LINEARIZABLE, explored, linearization)


def _unknown_candidates(
    operation: OperationRecord,
    operations: tuple[OperationRecord, ...],
) -> tuple[tuple[bool, OperationRecord | None], ...]:
    if not operation.is_inconclusive:
        return ((True, operation),)
    candidates: list[tuple[bool, OperationRecord | None]] = [(False, None)]
    request_path = urlsplit(operation.request.target).path
    if operation.request.method.upper() != "POST" or request_path != "/v1/events":
        return tuple(candidates)
    try:
        request = operation.request.json_body()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return tuple(candidates)
    if not isinstance(request, dict):
        return tuple(candidates)
    for evidence in operations:
        if evidence.response is None or evidence.response.status != 200:
            continue
        if evidence.request.method.upper() != "POST":
            continue
        if urlsplit(evidence.request.target).path != "/v1/events":
            continue
        try:
            evidence_request = evidence.request.json_body()
            evidence_body = evidence.response.json_body()
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(evidence_request, dict) or not isinstance(evidence_body, dict):
            continue
        if evidence_body.get("status") != "duplicate":
            continue
        if evidence_request.get("source") != request.get("source") or evidence_request.get(
            "batch_id"
        ) != request.get("batch_id"):
            continue
        try:
            same_fingerprint = SequentialModel._fingerprint(
                evidence_request
            ) == SequentialModel._fingerprint(request)
        except (KeyError, TypeError, ModelViolation):
            continue
        if not same_fingerprint:
            continue
        committed_body = dict(evidence_body)
        committed_body["status"] = "committed"
        inferred = replace(
            operation,
            response=ResponseRecord(
                200,
                evidence.response.headers,
                canonical_json(committed_body),
            ),
            transport_error=None,
            outcome_unknown=False,
        )
        candidates.append((True, inferred))
        break
    return tuple(candidates)


def _real_time_predecessors(
    operations: tuple[OperationRecord, ...],
) -> tuple[frozenset[int], ...]:
    predecessors: list[set[int]] = [set() for _ in operations]
    for earlier_index, earlier in enumerate(operations):
        for later_index, later in enumerate(operations):
            if earlier_index == later_index:
                continue
            if earlier.completed_monotonic_ns < later.invoked_monotonic_ns:
                predecessors[later_index].add(earlier_index)
    return tuple(frozenset(items) for items in predecessors)

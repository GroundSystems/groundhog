"""Durable operation histories for black-box verification."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterable, Mapping

from .transport import HttpResponse, TransportError, UnixHttpClient


FORMAT_VERSION = 1


def canonical_json(value: Any) -> bytes:
    """Encode one JSON value with stable object and whitespace ordering."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_bytes(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _ordered_headers(headers: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(((key.lower(), value) for key, value in headers), key=lambda item: item))


@dataclass(frozen=True)
class RequestRecord:
    method: str
    target: str
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def to_json(self) -> dict[str, Any]:
        return {
            "body_base64": _encode_bytes(self.body),
            "headers": [[key, value] for key, value in self.headers],
            "method": self.method,
            "target": self.target,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> RequestRecord:
        return cls(
            method=str(value["method"]),
            target=str(value["target"]),
            headers=tuple((str(key), str(item)) for key, item in value["headers"]),
            body=_decode_bytes(str(value["body_base64"])),
        )

    def json_body(self) -> Any:
        return json.loads(self.body)


@dataclass(frozen=True)
class ResponseRecord:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def to_json(self) -> dict[str, Any]:
        return {
            "body_base64": _encode_bytes(self.body),
            "headers": [[key, value] for key, value in self.headers],
            "status": self.status,
        }

    @classmethod
    def from_http(cls, response: HttpResponse) -> ResponseRecord:
        return cls(
            status=response.status,
            headers=_ordered_headers(response.headers),
            body=response.body,
        )

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> ResponseRecord:
        return cls(
            status=int(value["status"]),
            headers=tuple((str(key), str(item)) for key, item in value["headers"]),
            body=_decode_bytes(str(value["body_base64"])),
        )

    def json_body(self) -> Any:
        return json.loads(self.body)


@dataclass(frozen=True)
class OperationRecord:
    seed: int
    client_id: str
    operation_id: str
    invoked_monotonic_ns: int
    completed_monotonic_ns: int
    request: RequestRecord
    response: ResponseRecord | None
    transport_error: str | None = None
    outcome_unknown: bool = False

    def __post_init__(self) -> None:
        if self.completed_monotonic_ns < self.invoked_monotonic_ns:
            raise ValueError("operation completion precedes invocation")
        if (self.response is None) == (self.transport_error is None):
            raise ValueError("operation must contain one response or transport error")
        if self.response is not None and self.outcome_unknown:
            raise ValueError("a complete response cannot have an unknown outcome")

    @property
    def is_inconclusive(self) -> bool:
        return self.response is None and self.outcome_unknown

    def to_json(self) -> dict[str, Any]:
        if self.response is not None:
            outcome: dict[str, Any] = {
                "kind": "response",
                "response": self.response.to_json(),
            }
        else:
            outcome = {
                "kind": "transport_error",
                "message": self.transport_error,
                "outcome_unknown": self.outcome_unknown,
            }
        return {
            "client_id": self.client_id,
            "completed_monotonic_ns": self.completed_monotonic_ns,
            "invoked_monotonic_ns": self.invoked_monotonic_ns,
            "operation_id": self.operation_id,
            "outcome": outcome,
            "request": self.request.to_json(),
            "seed": self.seed,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> OperationRecord:
        outcome = value["outcome"]
        if outcome["kind"] == "response":
            response = ResponseRecord.from_json(outcome["response"])
            transport_error = None
            outcome_unknown = False
        elif outcome["kind"] == "transport_error":
            response = None
            transport_error = str(outcome["message"])
            outcome_unknown = bool(outcome["outcome_unknown"])
        else:
            raise ValueError(f"unknown history outcome: {outcome['kind']!r}")
        return cls(
            seed=int(value["seed"]),
            client_id=str(value["client_id"]),
            operation_id=str(value["operation_id"]),
            invoked_monotonic_ns=int(value["invoked_monotonic_ns"]),
            completed_monotonic_ns=int(value["completed_monotonic_ns"]),
            request=RequestRecord.from_json(value["request"]),
            response=response,
            transport_error=transport_error,
            outcome_unknown=outcome_unknown,
        )


class History:
    """An immutable verification history."""

    def __init__(self, seed: int, operations: Iterable[OperationRecord] = ()) -> None:
        self.seed = seed
        self.operations = tuple(operations)
        for operation in self.operations:
            if operation.seed != seed:
                raise ValueError("operation seed does not match history seed")
        identifiers = [operation.operation_id for operation in self.operations]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("history operation IDs are not unique")

    def to_json(self) -> dict[str, Any]:
        return {
            "operations": [operation.to_json() for operation in self.operations],
            "seed": self.seed,
            "v": FORMAT_VERSION,
        }

    def to_bytes(self) -> bytes:
        return canonical_json(self.to_json()) + b"\n"

    @classmethod
    def from_bytes(cls, encoded: bytes) -> History:
        value = json.loads(encoded)
        if value.get("v") != FORMAT_VERSION:
            raise ValueError(f"unsupported history version: {value.get('v')!r}")
        return cls(
            int(value["seed"]),
            (OperationRecord.from_json(item) for item in value["operations"]),
        )

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> History:
        return cls.from_bytes(Path(path).read_bytes())


class HistoryRecorder:
    """Record concurrent operations and durably replace one JSON history."""

    def __init__(self, path: str | os.PathLike[str], seed: int) -> None:
        self.path = Path(path)
        self.seed = seed
        self._operations: list[OperationRecord] = []
        self._operation_ids: set[str] = set()
        self._lock = threading.Lock()
        self._write_locked()

    def request(
        self,
        client: UnixHttpClient,
        *,
        client_id: str,
        operation_id: str,
        method: str,
        target: str,
        headers: Mapping[str, str] | None = None,
        body: bytes | str | None = None,
        json_body: Any | None = None,
    ) -> OperationRecord:
        request_headers = _ordered_headers((headers or {}).items())
        if json_body is not None:
            if body is not None:
                raise ValueError("body and json_body are mutually exclusive")
            body_bytes = canonical_json(json_body)
            wire_headers = dict(headers or {})
            wire_headers.setdefault("Content-Type", "application/json")
            request_headers = _ordered_headers(wire_headers.items())
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body or b""
        request = RequestRecord(
            method=method,
            target=target,
            headers=request_headers,
            body=body_bytes,
        )
        invoked = time.monotonic_ns()
        try:
            response = client.request(
                method,
                target,
                headers=dict(request_headers),
                body=body_bytes,
            )
            completed = time.monotonic_ns()
            operation = OperationRecord(
                seed=self.seed,
                client_id=client_id,
                operation_id=operation_id,
                invoked_monotonic_ns=invoked,
                completed_monotonic_ns=completed,
                request=request,
                response=ResponseRecord.from_http(response),
            )
        except TransportError as error:
            completed = time.monotonic_ns()
            operation = OperationRecord(
                seed=self.seed,
                client_id=client_id,
                operation_id=operation_id,
                invoked_monotonic_ns=invoked,
                completed_monotonic_ns=completed,
                request=request,
                response=None,
                transport_error=str(error),
                outcome_unknown=error.outcome_unknown,
            )
        self.append(operation)
        return operation

    def append(self, operation: OperationRecord) -> None:
        with self._lock:
            if operation.seed != self.seed:
                raise ValueError("operation seed does not match recorder seed")
            if operation.operation_id in self._operation_ids:
                raise ValueError(f"duplicate operation ID: {operation.operation_id}")
            self._operations.append(operation)
            self._operation_ids.add(operation.operation_id)
            self._write_locked()

    def history(self) -> History:
        with self._lock:
            return History(self.seed, tuple(self._operations))

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        encoded = History(self.seed, tuple(self._operations)).to_bytes()
        with temporary.open("wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

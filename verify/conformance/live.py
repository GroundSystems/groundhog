#!/usr/bin/env python3
"""Run the public HTTP contract against a Groundhog Unix-socket binary."""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openapi_schema_validator import OAS32Validator

from verify.conformance.validate import (
    DIALECT,
    ERROR_STATUSES,
    ContractError,
    load_document,
    validate_document,
)


class LiveError(AssertionError):
    """A live HTTP response did not match the public contract."""


_ACTIVE_RECORDER: BlackboxAdapter | None = None


@dataclass(frozen=True)
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body, object_pairs_hook=_unique_json_object)
        except (UnicodeError, json.JSONDecodeError, LiveError) as error:
            raise LiveError(f"response body is not JSON: {error}") from error


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LiveError(f"JSON contains duplicate member {key!r}")
        value[key] = item
    return value


def _decode_chunked(payload: bytes) -> bytes:
    body = bytearray()
    remaining = payload
    while True:
        line_end = remaining.find(b"\r\n")
        if line_end < 0:
            raise LiveError("chunked response has no size terminator")
        raw_size = remaining[:line_end].split(b";", 1)[0]
        try:
            size = int(raw_size, 16)
        except ValueError as error:
            raise LiveError("chunked response has an invalid size") from error
        remaining = remaining[line_end + 2 :]
        if size == 0:
            return bytes(body)
        if len(remaining) < size + 2 or remaining[size : size + 2] != b"\r\n":
            raise LiveError("chunked response has an incomplete chunk")
        body.extend(remaining[:size])
        remaining = remaining[size + 2 :]


def parse_response(raw: bytes) -> RawResponse:
    """Parse one complete HTTP/1.1 response."""
    split = raw.find(b"\r\n\r\n")
    if split < 0:
        raise LiveError("response has no header terminator")
    try:
        lines = raw[:split].decode("ascii").split("\r\n")
        status = int(lines[0].split()[1])
    except (UnicodeError, ValueError, IndexError) as error:
        raise LiveError("response has an invalid status line") from error
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            raise LiveError(f"response has an invalid header: {line!r}")
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    payload = raw[split + 4 :]
    if headers.get("transfer-encoding", "").lower() == "chunked":
        payload = _decode_chunked(payload)
    return RawResponse(status, headers, payload)


def build_request(
    method: str,
    target: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> bytes:
    """Build one raw HTTP/1.1 request with explicit bytes."""
    selected = {"Host": "groundhog", "Connection": "close"}
    if headers:
        selected.update(headers)
    if body and not any(name.lower() == "content-length" for name in selected):
        selected["Content-Length"] = str(len(body))
    head = f"{method} {target} HTTP/1.1\r\n"
    head += "".join(f"{name}: {value}\r\n" for name, value in selected.items())
    return head.encode("ascii") + b"\r\n" + body


def send_raw(socket_path: Path, request: bytes) -> RawResponse:
    """Send one raw request and read its complete response."""
    invoked = time.monotonic_ns()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(socket_path))
        connection.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    response = parse_response(b"".join(chunks))
    completed = time.monotonic_ns()
    if _ACTIVE_RECORDER is not None:
        _ACTIVE_RECORDER.record(request, response, invoked, completed)
    return response


def request_json(
    socket_path: Path,
    method: str,
    target: str,
    value: Any | None = None,
    headers: dict[str, str] | None = None,
) -> RawResponse:
    body = b"" if value is None else json.dumps(value, separators=(",", ":")).encode()
    selected_headers = {"Content-Type": "application/json"}
    if headers:
        selected_headers.update(headers)
    return send_raw(
        socket_path,
        build_request(method, target, body, selected_headers),
    )


class SchemaChecker:
    """Validate live JSON values against schemas in one OpenAPI document."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def check(self, reference: str, value: Any, label: str) -> None:
        wrapper = {
            "$schema": DIALECT,
            "$ref": reference,
            "components": self.document["components"],
        }
        errors = sorted(OAS32Validator(wrapper).iter_errors(value), key=str)
        if errors:
            rendered = "; ".join(error.message for error in errors)
            raise LiveError(f"{label} does not match {reference}: {rendered}")


class BlackboxAdapter:
    """Send compatible finite operations to the public black-box recorder."""

    def __init__(self, path: Path, seed: int) -> None:
        history = importlib.import_module("verify.blackbox.history")
        linearizability = importlib.import_module("verify.blackbox.linearizability")
        self.history = history
        self.linearizability = linearizability
        self.recorder = history.HistoryRecorder(path, seed)
        self.seed = seed
        self.next_id = 0

    @staticmethod
    def _request_parts(raw: bytes) -> tuple[str, str, tuple[tuple[str, str], ...], bytes]:
        split = raw.find(b"\r\n\r\n")
        if split < 0:
            raise LiveError("recorded request has no header terminator")
        try:
            lines = raw[:split].decode("iso-8859-1").split("\r\n")
            method, target, _version = lines[0].split(" ", 2)
        except (UnicodeError, ValueError) as error:
            raise LiveError("recorded request has an invalid request line") from error
        headers = []
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if not separator:
                raise LiveError("recorded request has an invalid header")
            headers.append((name.strip().lower(), value.strip()))
        return method, target, tuple(sorted(headers)), raw[split + 4 :]

    @staticmethod
    def _recordable(method: str, target: str, body: bytes, status: int) -> bool:
        path = urllib.parse.urlsplit(target).path
        if method == "GET" and path in {"/v1/events", "/v1/streams"}:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query)
            return status == 200 and query.get("follow") != ["true"]
        if method == "POST" and path == "/v1/events":
            if status not in {200, 409}:
                return False
        elif method == "POST" and path == "/v1/sources/retire":
            if status not in {200, 404}:
                return False
        else:
            return False
        try:
            return isinstance(json.loads(body), dict)
        except (UnicodeError, json.JSONDecodeError):
            return False

    def record(
        self, raw: bytes, response: RawResponse, invoked: int, completed: int
    ) -> None:
        method, target, headers, body = self._request_parts(raw)
        if not self._recordable(method, target, body, response.status):
            return
        if response.status == 409:
            response_body = response.json()
            if response_body.get("error") == "source_lineage_conflict":
                return
        self.next_id += 1
        request = self.history.RequestRecord(method, target, headers, body)
        recorded_response = self.history.ResponseRecord(
            response.status, tuple(sorted(response.headers.items())), response.body
        )
        operation = self.history.OperationRecord(
            seed=self.seed,
            client_id="openapi-conformance",
            operation_id=f"openapi-{self.next_id:04d}",
            invoked_monotonic_ns=invoked,
            completed_monotonic_ns=completed,
            request=request,
            response=recorded_response,
        )
        self.recorder.append(operation)

    def require_linearizable(self) -> None:
        result = self.linearizability.check_history(self.recorder.history())
        status = getattr(result.status, "value", str(result.status))
        if status != "linearizable":
            raise LiveError(f"recorded black-box history is {status}: {result.reason}")


def assert_status(response: RawResponse, expected: int, label: str) -> None:
    if response.status != expected:
        raise LiveError(f"{label} returned {response.status}, expected {expected}: {response.body!r}")


def assert_json(
    response: RawResponse,
    expected_status: int,
    schema: str,
    checker: SchemaChecker,
    label: str,
) -> Any:
    assert_status(response, expected_status, label)
    if not response.headers.get("content-type", "").startswith("application/json"):
        raise LiveError(f"{label} did not return application/json")
    value = response.json()
    checker.check(schema, value, label)
    return value


def assert_error(
    response: RawResponse,
    expected_status: int,
    expected_code: str,
    checker: SchemaChecker,
    label: str,
) -> Any:
    value = assert_json(
        response, expected_status, "#/components/schemas/Error", checker, label
    )
    if value.get("error") != expected_code:
        raise LiveError(f"{label} returned error {value.get('error')!r}, expected {expected_code!r}")
    if ERROR_STATUSES.get(expected_code) != expected_status:
        raise LiveError(f"{label} uses an incorrect stable error status")
    return value


def assert_replay_invariants(
    value: dict[str, Any], label: str, after: str | None = None
) -> None:
    """Check cursor and frontier relationships that JSON Schema cannot express."""
    events = value["events"]
    event_ids = [item["event_id"] for item in events]
    if event_ids != sorted(set(event_ids)):
        raise LiveError(f"{label} events are not in strict event order")
    last_event_id = value.get("last_event_id")
    if bool(events) != (last_event_id is not None):
        raise LiveError(f"{label} last_event_id does not match event presence")
    if events and last_event_id != event_ids[-1]:
        raise LiveError(f"{label} last_event_id is not the final returned event")
    frontier = value["snapshot_through_event_id"]
    if event_ids and (frontier is None or event_ids[-1] > frontier):
        raise LiveError(f"{label} returned an event after its snapshot frontier")
    next_after = value["next_after"]
    if last_event_id is not None and (next_after is None or next_after < last_event_id):
        raise LiveError(f"{label} next_after precedes last_event_id")
    if after is not None and (next_after is None or next_after < after):
        raise LiveError(f"{label} next_after precedes the request cursor")


class NdjsonResponse:
    """Read NDJSON records independently from HTTP chunk boundaries."""

    def __init__(self, socket_path: Path, target: str) -> None:
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.settimeout(5)
        self.connection.connect(str(socket_path))
        self.connection.sendall(build_request("GET", target))
        self.reader = self.connection.makefile("rb")
        status_line = self.reader.readline()
        try:
            self.status = int(status_line.split()[1])
        except (ValueError, IndexError) as error:
            self.close()
            raise LiveError("follow response has an invalid status line") from error
        self.headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if line == b"\r\n":
                break
            if not line:
                self.close()
                raise LiveError("follow response ended before its headers")
            name, separator, value = line.partition(b":")
            if not separator:
                self.close()
                raise LiveError("follow response has an invalid header")
            self.headers[name.decode("ascii").lower()] = value.decode("ascii").strip()
        if self.headers.get("transfer-encoding", "").lower() != "chunked":
            self.close()
            raise LiveError("follow response is not chunked")
        self.pending = bytearray()

    def _next_chunk(self) -> bytes:
        size_line = self.reader.readline()
        if not size_line:
            raise LiveError("follow response ended before the next record")
        try:
            size = int(size_line.strip().split(b";", 1)[0], 16)
        except ValueError as error:
            raise LiveError("follow response has an invalid chunk size") from error
        if size == 0:
            raise LiveError("follow response ended before the next record")
        data = self.reader.read(size)
        if len(data) != size or self.reader.read(2) != b"\r\n":
            raise LiveError("follow response has an incomplete chunk")
        return data

    def next_json(self) -> Any:
        while b"\n" not in self.pending:
            self.pending.extend(self._next_chunk())
        line, _, remaining = self.pending.partition(b"\n")
        self.pending = bytearray(remaining)
        try:
            return json.loads(line, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, LiveError) as error:
            raise LiveError(f"follow record is not JSON: {error}") from error

    def close(self) -> None:
        reader = getattr(self, "reader", None)
        if reader is not None:
            reader.close()
        self.connection.close()

    def __enter__(self) -> NdjsonResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class GroundhogProcess:
    """Create and serve one disposable Groundhog deployment."""

    def __init__(self, binary: Path, token: str | None = None) -> None:
        self.binary = binary.resolve()
        self.token = token
        self.root = Path(tempfile.mkdtemp(prefix="groundhog-conformance-", dir="/private/tmp"))
        self.socket = self.root / "data" / "ground.sock"
        self.log_path = self.root / "server.log"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_file: Any = None

    def start(self) -> None:
        initialized = subprocess.run(
            [str(self.binary), "init", str(self.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if initialized.returncode != 0:
            raise LiveError(f"groundhog init failed: {initialized.stderr.decode(errors='replace')}")
        if self.token is not None:
            config_path = self.root / "groundhog.toml"
            config = config_path.read_text(encoding="utf-8")
            marker = 'token = ""'
            if marker not in config:
                raise LiveError("groundhog init did not write the expected token setting")
            config_path.write_text(
                config.replace(marker, f'token = "{self.token}"', 1),
                encoding="utf-8",
            )
        self.log_file = self.log_path.open("wb")
        self.process = subprocess.Popen(
            [str(self.binary), "--config", str(self.root / "groundhog.toml"), "serve"],
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.connect(str(self.socket))
                return
            except OSError:
                time.sleep(0.02)
        self.stop()
        detail = self.log_path.read_text(encoding="utf-8", errors="replace")
        raise LiveError(f"groundhog serve did not open its socket: {detail}")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log_file is not None:
            self.log_file.close()

    def close(self) -> None:
        self.stop()
        shutil.rmtree(self.root)

    def __enter__(self) -> GroundhogProcess:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def event(stream: str, record_key: str, payload: Any) -> dict[str, Any]:
    return {
        "stream": stream,
        "record_key": record_key,
        "kind": "upserted",
        "payload": payload,
    }


def append_body(
    batch_id: str, source: str, events: list[dict[str, Any]]
) -> dict[str, Any]:
    return {"v": 1, "batch_id": batch_id, "source": source, "events": events}


def _check_raw_errors(server: GroundhogProcess, checker: SchemaChecker) -> None:
    query_body = json.dumps(append_body("query", "raw", [event("items", "1", 1)])).encode()
    assert_error(
        send_raw(server.socket, build_request("POST", "/v1/events?limit=1", query_body)),
        400,
        "invalid_request",
        checker,
        "append query",
    )
    assert_error(
        send_raw(server.socket, build_request("GET", "/v1/events?source=%")),
        400,
        "invalid_request",
        checker,
        "malformed query",
    )
    duplicate = (
        b'{"v":1,"batch_id":"duplicate","batch_id":"other","source":"raw",'
        b'"events":[{"stream":"items","record_key":"1","kind":"upserted",'
        b'"payload":{"a":1,"a":2}}]}'
    )
    assert_error(
        send_raw(
            server.socket,
            build_request("POST", "/v1/events", duplicate, {"Content-Type": "application/json"}),
        ),
        400,
        "invalid_request",
        checker,
        "duplicate JSON member",
    )
    assert_error(
        request_json(server.socket, "GET", "/v1/events?limit=0"),
        400,
        "invalid_replay_request",
        checker,
        "invalid replay limit",
    )
    assert_error(
        request_json(server.socket, "GET", "/v1/events?source=a&source=b"),
        400,
        "invalid_request",
        checker,
        "repeated replay parameter",
    )
    assert_error(
        request_json(server.socket, "GET", "/v1/not-a-route"),
        404,
        "not_found",
        checker,
        "unknown route",
    )
    wrong_method = send_raw(server.socket, build_request("DELETE", "/v1/events"))
    assert_error(wrong_method, 405, "method_not_allowed", checker, "wrong method")
    allow = {item.strip() for item in wrong_method.headers.get("allow", "").split(",")}
    if not {"GET", "HEAD", "POST"}.issubset(allow):
        raise LiveError("wrong method did not return the complete Allow header")

    media_body = json.dumps(
        append_body("media", "raw", [event("items", "media", 1)])
    ).encode()
    assert_error(
        send_raw(
            server.socket,
            build_request(
                "POST", "/v1/events", media_body, {"Content-Type": "text/plain"}
            ),
        ),
        415,
        "unsupported_media_type",
        checker,
        "unsupported append media type",
    )

    for label, payload in (
        ("non-finite number", b"1e400"),
        ("precision-losing integer", b"9007199254740993"),
    ):
        body = (
            b'{"v":1,"batch_id":"number-'
            + label.replace(" ", "-").encode()
            + b'","source":"raw","events":[{"stream":"items",'
            b'"record_key":"number","kind":"upserted","payload":'
            + payload
            + b'}]}'
        )
        assert_error(
            send_raw(
                server.socket,
                build_request(
                    "POST", "/v1/events", body, {"Content-Type": "application/json"}
                ),
            ),
            400,
            "invalid_request",
            checker,
            label,
        )

    deep_payload = b"[" * 129 + b"0" + b"]" * 129
    deep_body = (
        b'{"v":1,"batch_id":"depth","source":"raw","events":[{"stream":"items",'
        b'"record_key":"depth","kind":"upserted","payload":'
        + deep_payload
        + b'}]}'
    )
    depth_error = assert_error(
        send_raw(
            server.socket,
            build_request(
                "POST", "/v1/events", deep_body, {"Content-Type": "application/json"}
            ),
        ),
        400,
        "invalid_events",
        checker,
        "payload depth",
    )
    if depth_error["errors"][0]["index"] != 0:
        raise LiveError("payload depth error did not identify event zero")

    invalid_time = append_body("time", "raw", [event("items", "time", 1)])
    invalid_time["events"][0]["occurred_at"] = "2026-02-30T00:00:00Z"
    time_error = assert_error(
        request_json(server.socket, "POST", "/v1/events", invalid_time),
        400,
        "invalid_events",
        checker,
        "invalid calendar timestamp",
    )
    if time_error["errors"][0]["index"] != 0:
        raise LiveError("calendar timestamp error did not identify event zero")

    mixed = append_body(
        "mixed-precondition",
        "raw",
        [event("items", "one", 1), event("other", "two", 2)],
    )
    mixed["stream_precondition"] = {"stream": "items", "expected_frontier": None}
    assert_error(
        request_json(server.socket, "POST", "/v1/events", mixed),
        400,
        "invalid_batch",
        checker,
        "mixed precondition streams",
    )

    head_error = send_raw(
        server.socket, build_request("HEAD", "/v1/events?source=a&source=b")
    )
    assert_status(head_error, 400, "HEAD replay error")
    if head_error.body:
        raise LiveError("HEAD replay error returned a body")


def _check_authentication(binary: Path, checker: SchemaChecker) -> None:
    token = "conformance-token"
    with GroundhogProcess(binary, token=token) as server:
        unauthorized = assert_error(
            send_raw(server.socket, build_request("GET", "/v1/events")),
            401,
            "unauthorized",
            checker,
            "missing bearer token",
        )
        wrong = assert_error(
            send_raw(
                server.socket,
                build_request(
                    "GET",
                    "/v1/not-a-route",
                    headers={"Authorization": "Bearer wrong"},
                ),
            ),
            401,
            "unauthorized",
            checker,
            "incorrect bearer token",
        )
        if wrong != unauthorized:
            raise LiveError("authorization exposed route state before authentication")
        authorized = assert_json(
            send_raw(
                server.socket,
                build_request(
                    "GET",
                    "/v1/events",
                    headers={"Authorization": f"Bearer {token}"},
                ),
            ),
            200,
            "#/components/schemas/ReplayResponse",
            checker,
            "valid bearer token",
        )
        assert_replay_invariants(authorized, "valid bearer token")


def _check_append_and_replay(server: GroundhogProcess, checker: SchemaChecker) -> None:
    body = append_body("append-success", "append_source", [event("items", "1", {"id": 1})])
    committed = assert_json(
        request_json(server.socket, "POST", "/v1/events", body),
        200,
        "#/components/schemas/AppendReceipt",
        checker,
        "append",
    )
    if committed["status"] != "committed":
        raise LiveError("the first append did not return committed")
    duplicate = assert_json(
        request_json(server.socket, "POST", "/v1/events", body),
        200,
        "#/components/schemas/AppendReceipt",
        checker,
        "append retry",
    )
    if duplicate["status"] != "duplicate" or duplicate["last_event_id"] != committed["last_event_id"]:
        raise LiveError("the append retry did not return the original receipt")
    changed = append_body(
        "append-success", "append_source", [event("items", "changed", {"id": 2})]
    )
    conflict = assert_error(
        request_json(server.socket, "POST", "/v1/events", changed),
        409,
        "batch_id_conflict",
        checker,
        "batch identity conflict",
    )
    if conflict.get("source") != "append_source" or conflict.get("batch_id") != "append-success":
        raise LiveError("batch identity conflict omitted its stable context")

    conditional = append_body(
        "precondition-conflict", "append_source", [event("items", "2", {"id": 2})]
    )
    conditional["stream_precondition"] = {
        "stream": "items",
        "expected_frontier": None,
    }
    precondition = assert_error(
        request_json(server.socket, "POST", "/v1/events", conditional),
        409,
        "stream_frontier_conflict",
        checker,
        "stream frontier conflict",
    )
    expected_context = {
        "source": "append_source",
        "stream": "items",
        "expected_frontier": None,
        "actual_frontier": committed["last_event_id"],
    }
    if any(precondition.get(key) != value for key, value in expected_context.items()):
        raise LiveError("stream frontier conflict omitted its stable context")

    finite_response = request_json(server.socket, "GET", "/v1/events?source=append_source")
    finite = assert_json(
        finite_response,
        200,
        "#/components/schemas/ReplayResponse",
        checker,
        "finite replay",
    )
    assert_replay_invariants(finite, "finite replay")
    if len(finite["events"]) != 1 or finite["events"][0]["source"] != "append_source":
        raise LiveError("finite replay did not return the appended event")
    head = request_json(server.socket, "HEAD", "/v1/events?source=append_source")
    assert_status(head, 200, "HEAD replay")
    if head.body:
        raise LiveError("HEAD replay returned a body")


def _check_pagination(server: GroundhogProcess, checker: SchemaChecker) -> None:
    batch = append_body(
        "event-pages",
        "event_pages",
        [event("items", str(index), {"index": index}) for index in range(3)],
    )
    assert_status(request_json(server.socket, "POST", "/v1/events", batch), 200, "page seed")
    first = assert_json(
        request_json(server.socket, "GET", "/v1/events?source=event_pages&limit=2"),
        200,
        "#/components/schemas/ReplayResponse",
        checker,
        "first replay page",
    )
    assert_replay_invariants(first, "first replay page")
    first_cursor = first["next_after"]
    second = assert_json(
        request_json(
            server.socket,
            "GET",
            f"/v1/events?source=event_pages&limit=2&after={first_cursor}",
        ),
        200,
        "#/components/schemas/ReplayResponse",
        checker,
        "second replay page",
    )
    assert_replay_invariants(second, "second replay page", first_cursor)
    event_ids = [item["event_id"] for item in first["events"] + second["events"]]
    if len(event_ids) != 3 or event_ids != sorted(set(event_ids)):
        raise LiveError("finite replay pagination lost, duplicated, or reordered events")

    streams = append_body(
        "stream-pages",
        "stream_pages",
        [event(name, name, name) for name in ("a", "c", "d")],
    )
    assert_status(request_json(server.socket, "POST", "/v1/events", streams), 200, "stream seed")
    stream_seed_replay = assert_json(
        request_json(server.socket, "GET", "/v1/events?source=stream_pages"),
        200,
        "#/components/schemas/ReplayResponse",
        checker,
        "stream seed replay",
    )
    assert_replay_invariants(stream_seed_replay, "stream seed replay")
    page_one = assert_json(
        request_json(server.socket, "GET", "/v1/streams?source=stream_pages&limit=1"),
        200,
        "#/components/schemas/StreamsResponse",
        checker,
        "first streams page",
    )
    later = append_body("stream-later", "stream_pages", [event("b", "b", "b")])
    assert_status(request_json(server.socket, "POST", "/v1/events", later), 200, "later stream")
    after = urllib.parse.quote(page_one["next_after"], safe="")
    through = page_one["snapshot_through_event_id"]
    page_two = assert_json(
        request_json(
            server.socket,
            "GET",
            f"/v1/streams?source=stream_pages&limit=10&after={after}&through={through}",
        ),
        200,
        "#/components/schemas/StreamsResponse",
        checker,
        "second streams page",
    )
    if [row["stream"] for row in page_two["streams"]] != ["c", "d"]:
        raise LiveError("anchored stream pagination included later state")
    head = request_json(server.socket, "HEAD", "/v1/streams?source=stream_pages")
    assert_status(head, 200, "HEAD streams")
    if head.body:
        raise LiveError("HEAD streams returned a body")


def _check_follow(server: GroundhogProcess, checker: SchemaChecker) -> None:
    initial = append_body("follow-initial", "follow_source", [event("items", "1", 1)])
    assert_status(request_json(server.socket, "POST", "/v1/events", initial), 200, "follow seed")
    with NdjsonResponse(server.socket, "/v1/events?source=follow_source&follow=true&limit=10") as follow:
        assert_status(RawResponse(follow.status, follow.headers, b""), 200, "follow")
        if follow.headers.get("content-type") != "application/x-ndjson":
            raise LiveError("follow did not return application/x-ndjson")
        if follow.headers.get("cache-control") != "no-store":
            raise LiveError("follow did not return Cache-Control: no-store")
        if follow.headers.get("connection") != "close":
            raise LiveError("follow did not return Connection: close")
        snapshot = follow.next_json()
        checker.check("#/components/schemas/FollowRecord", snapshot, "follow snapshot")
        if snapshot.get("type") != "events" or snapshot.get("phase") != "snapshot":
            raise LiveError("follow did not start with a snapshot event record")
        caught_up = follow.next_json()
        checker.check("#/components/schemas/FollowRecord", caught_up, "follow caught-up")
        if caught_up.get("type") != "caught_up":
            raise LiveError("follow did not emit a caught-up record")
        live_batch = append_body("follow-live", "follow_source", [event("items", "2", 2)])
        assert_status(request_json(server.socket, "POST", "/v1/events", live_batch), 200, "live append")
        live = follow.next_json()
        checker.check("#/components/schemas/FollowRecord", live, "follow live")
        if live.get("type") != "events" or live.get("phase") != "live":
            raise LiveError("follow did not emit a live event record")
        server.stop()
        terminal = follow.next_json()
        checker.check("#/components/schemas/FollowRecord", terminal, "follow terminal")
        if terminal.get("type") != "end" or terminal.get("reason") != "shutdown":
            raise LiveError("follow did not emit its shutdown terminal record")


def _check_lifecycle_and_lineage(server: GroundhogProcess, checker: SchemaChecker) -> None:
    predecessor = append_body("predecessor", "agent_old", [event("records", "1", 1)])
    receipt = assert_json(
        request_json(server.socket, "POST", "/v1/events", predecessor),
        200,
        "#/components/schemas/AppendReceipt",
        checker,
        "predecessor append",
    )
    retirement_request = {"v": 1, "source": "agent_old"}
    retired = assert_json(
        request_json(server.socket, "POST", "/v1/sources/retire", retirement_request),
        200,
        "#/components/schemas/RetirementResponse",
        checker,
        "retirement",
    )
    if retired["status"] != "retired" or retired["final_frontier"] != receipt["last_event_id"]:
        raise LiveError("retirement did not use the source frontier")
    repeated = assert_json(
        request_json(server.socket, "POST", "/v1/sources/retire", retirement_request),
        200,
        "#/components/schemas/RetirementResponse",
        checker,
        "retirement retry",
    )
    if repeated["status"] != "already_retired" or repeated["retirement_event_id"] != retired[
        "retirement_event_id"
    ]:
        raise LiveError("retirement retry did not return the durable record")
    refused = append_body("after-retirement", "agent_old", [event("records", "2", 2)])
    retired_error = assert_error(
        request_json(server.socket, "POST", "/v1/events", refused),
        409,
        "source_retired",
        checker,
        "append after retirement",
    )
    if any(
        retired_error.get(key) != value
        for key, value in {
            "source": "agent_old",
            "final_frontier": retired["final_frontier"],
            "retirement_event_id": retired["retirement_event_id"],
        }.items()
    ):
        raise LiveError("source-retired error omitted its stable context")

    lifecycle_replay = assert_json(
        request_json(
            server.socket,
            "GET",
            "/v1/events?source=system&stream=groundhog.source_lifecycle",
        ),
        200,
        "#/components/schemas/ReplayResponse",
        checker,
        "retirement event replay",
    )
    assert_replay_invariants(lifecycle_replay, "retirement event replay")
    retirement_event = lifecycle_replay["events"][-1]
    expected_retirement = {
        "source": "system",
        "stream": "groundhog.source_lifecycle",
        "record_key": "agent_old",
        "kind": "source_retired",
        "batch_id": f"groundhog/retire/agent_old/{retired['final_frontier']}",
        "payload": {
            "v": 1,
            "source": "agent_old",
            "final_frontier": retired["final_frontier"],
        },
    }
    if any(retirement_event.get(key) != value for key, value in expected_retirement.items()):
        raise LiveError("retirement event does not match its documented envelope")
    if "occurred_at" in retirement_event:
        raise LiveError("retirement event contains occurred_at")

    lineage = {
        "stream": "groundhog.source_lineage",
        "record_key": "agent_old",
        "kind": "source_succeeded",
        "payload": {
            "v": 1,
            "predecessor_source": "agent_old",
            "predecessor_final_frontier": retired["final_frontier"],
        },
    }
    successor = append_body(
        "successor", "agent_new", [lineage, event("records", "first", {"ok": True})]
    )
    assert_json(
        request_json(server.socket, "POST", "/v1/events", successor),
        200,
        "#/components/schemas/AppendReceipt",
        checker,
        "successor lineage append",
    )
    replay = assert_json(
        request_json(server.socket, "GET", "/v1/events?source=agent_new"),
        200,
        "#/components/schemas/ReplayResponse",
        checker,
        "successor replay",
    )
    assert_replay_invariants(replay, "successor replay")
    if replay["events"][0]["stream"] != "groundhog.source_lineage":
        raise LiveError("the lineage event is not the successor's first event")

    malformed = append_body(
        "bad-lineage",
        "agent_bad",
        [event("records", "first", 1), lineage],
    )
    assert_error(
        request_json(server.socket, "POST", "/v1/events", malformed),
        400,
        "invalid_source_lineage",
        checker,
        "malformed lineage",
    )

    duplicate_lineage = append_body(
        "duplicate-lineage", "agent_duplicate", [lineage, lineage]
    )
    assert_error(
        request_json(server.socket, "POST", "/v1/events", duplicate_lineage),
        400,
        "invalid_source_lineage",
        checker,
        "duplicate lineage marker",
    )

    timed_lineage = json.loads(json.dumps(lineage))
    timed_lineage["occurred_at"] = "2026-07-29T00:00:00Z"
    assert_error(
        request_json(
            server.socket,
            "POST",
            "/v1/events",
            append_body("timed-lineage", "agent_timed", [timed_lineage]),
        ),
        400,
        "invalid_source_lineage",
        checker,
        "lineage occurred_at",
    )

    self_lineage = json.loads(json.dumps(lineage))
    self_lineage["record_key"] = "agent_self"
    self_lineage["payload"]["predecessor_source"] = "agent_self"
    assert_error(
        request_json(
            server.socket,
            "POST",
            "/v1/events",
            append_body("self-lineage", "agent_self", [self_lineage]),
        ),
        400,
        "invalid_source_lineage",
        checker,
        "self lineage",
    )

    wrong_frontier = json.loads(json.dumps(lineage))
    wrong_frontier["payload"]["predecessor_final_frontier"] = retired[
        "retirement_event_id"
    ]
    lineage_conflict = assert_error(
        request_json(
            server.socket,
            "POST",
            "/v1/events",
            append_body("wrong-frontier", "agent_wrong", [wrong_frontier]),
        ),
        409,
        "source_lineage_conflict",
        checker,
        "lineage frontier conflict",
    )
    if lineage_conflict.get("actual_predecessor_frontier") != retired["final_frontier"]:
        raise LiveError("lineage conflict omitted the actual predecessor frontier")


def run(
    binary: Path,
    document_path: Path,
    history_path: Path | None = None,
    history_seed: int = 0,
) -> None:
    """Run all live conformance checks."""
    if not binary.is_file():
        raise LiveError(f"binary does not exist: {binary}")
    document = load_document(document_path)
    validate_document(document)
    checker = SchemaChecker(document)
    _check_authentication(binary, checker)
    recorder = None if history_path is None else BlackboxAdapter(history_path, history_seed)
    global _ACTIVE_RECORDER
    _ACTIVE_RECORDER = recorder
    try:
        with GroundhogProcess(binary) as server:
            empty = assert_json(
                request_json(server.socket, "GET", "/v1/events"),
                200,
                "#/components/schemas/ReplayResponse",
                checker,
                "empty replay",
            )
            if empty != {"events": [], "next_after": None, "snapshot_through_event_id": None}:
                raise LiveError("empty replay has an unexpected shape")
            _check_raw_errors(server, checker)
            _check_append_and_replay(server, checker)
            _check_pagination(server, checker)
            _check_lifecycle_and_lineage(server, checker)
            _check_follow(server, checker)
        if recorder is not None:
            recorder.require_linearizable()
    finally:
        _ACTIVE_RECORDER = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("target/debug/groundhog"))
    parser.add_argument("--document", type=Path, default=Path("openapi.yaml"))
    parser.add_argument("--history", type=Path)
    parser.add_argument("--history-seed", type=int, default=0)
    arguments = parser.parse_args()
    try:
        run(arguments.binary, arguments.document, arguments.history, arguments.history_seed)
    except (ContractError, LiveError, OSError) as error:
        print(error)
        return 1
    print(f"validated {arguments.binary} against {arguments.document}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

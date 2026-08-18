"""External process and Unix-socket HTTP transport support."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, Mapping

from verify.backend import BackendOptions


@dataclass(frozen=True)
class HttpResponse:
    """One complete HTTP response."""

    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers:
            if key.lower() == lowered:
                return value
        return None

    def json(self) -> Any:
        return json.loads(self.body)


class TransportError(RuntimeError):
    """A transport failure with an explicit outcome certainty."""

    def __init__(self, message: str, *, outcome_unknown: bool) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


class UnixHttpClient:
    """A small HTTP/1.1 client for a Unix-domain socket."""

    def __init__(self, socket_path: str | os.PathLike[str], timeout: float = 5.0) -> None:
        self.socket_path = Path(socket_path)
        self.timeout = timeout

    def request(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | str | None = None,
        json_body: Any | None = None,
    ) -> HttpResponse:
        if body is not None and json_body is not None:
            raise ValueError("body and json_body are mutually exclusive")
        request_headers = {key: value for key, value in (headers or {}).items()}
        if json_body is not None:
            body_bytes = json.dumps(
                json_body, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body or b""
        request_headers.setdefault("Host", "groundhog")
        request_headers.setdefault("Connection", "close")
        request_headers["Content-Length"] = str(len(body_bytes))
        head = [f"{method} {target} HTTP/1.1"]
        head.extend(f"{key}: {value}" for key, value in request_headers.items())
        wire = ("\r\n".join(head) + "\r\n\r\n").encode("ascii") + body_bytes

        connected = False
        sent = False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(self.timeout)
                stream.connect(str(self.socket_path))
                connected = True
                sent = True
                stream.sendall(wire)
                return self._read_response(stream, expect_body=method.upper() != "HEAD")
        except (OSError, ValueError) as error:
            phase = "response" if sent else "request" if connected else "connect"
            raise TransportError(
                f"Unix HTTP {phase} failed: {error}", outcome_unknown=sent
            ) from error

    def _read_response(
        self, stream: socket.socket, *, expect_body: bool = True
    ) -> HttpResponse:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            part = stream.recv(65536)
            if not part:
                raise ValueError("response ended before the HTTP header terminator")
            buffer.extend(part)
        split = buffer.index(b"\r\n\r\n")
        head = bytes(buffer[:split]).decode("iso-8859-1")
        pending = bytes(buffer[split + 4 :])
        lines = head.split("\r\n")
        status_parts = lines[0].split(" ", 2)
        if len(status_parts) < 2 or not status_parts[1].isdigit():
            raise ValueError(f"invalid HTTP status line: {lines[0]!r}")
        status = int(status_parts[1])
        reason = status_parts[2] if len(status_parts) == 3 else ""
        parsed_headers: list[tuple[str, str]] = []
        for line in lines[1:]:
            if ":" not in line:
                raise ValueError(f"invalid HTTP header: {line!r}")
            name, value = line.split(":", 1)
            parsed_headers.append((name.lower(), value.strip()))
        headers = tuple(parsed_headers)
        if not expect_body:
            return HttpResponse(status=status, reason=reason, headers=headers, body=b"")
        transfer_encoding = self._header(headers, "transfer-encoding")
        content_length = self._header(headers, "content-length")
        if transfer_encoding and "chunked" in transfer_encoding.lower():
            body = self._read_chunked(stream, pending)
        elif content_length is not None:
            expected = int(content_length)
            body = self._read_exact(stream, pending, expected)
        else:
            chunks = [pending]
            while True:
                part = stream.recv(65536)
                if not part:
                    break
                chunks.append(part)
            body = b"".join(chunks)
        return HttpResponse(status=status, reason=reason, headers=headers, body=body)

    @staticmethod
    def _header(headers: tuple[tuple[str, str], ...], name: str) -> str | None:
        for key, value in headers:
            if key == name:
                return value
        return None

    @staticmethod
    def _read_exact(stream: socket.socket, pending: bytes, expected: int) -> bytes:
        body = bytearray(pending)
        while len(body) < expected:
            part = stream.recv(min(65536, expected - len(body)))
            if not part:
                raise ValueError("response ended before its declared content length")
            body.extend(part)
        if len(body) != expected:
            raise ValueError("response exceeded its declared content length")
        return bytes(body)

    @staticmethod
    def _read_chunked(stream: socket.socket, pending: bytes) -> bytes:
        buffer = bytearray(pending)
        decoded = bytearray()

        def fill_until(marker: bytes) -> None:
            while marker not in buffer:
                part = stream.recv(65536)
                if not part:
                    raise ValueError("chunked response ended early")
                buffer.extend(part)

        while True:
            fill_until(b"\r\n")
            line_end = buffer.index(b"\r\n")
            size_line = bytes(buffer[:line_end]).split(b";", 1)[0]
            del buffer[: line_end + 2]
            try:
                size = int(size_line, 16)
            except ValueError as error:
                raise ValueError(f"invalid HTTP chunk size: {size_line!r}") from error
            if size == 0:
                fill_until(b"\r\n")
                return bytes(decoded)
            while len(buffer) < size + 2:
                part = stream.recv(65536)
                if not part:
                    raise ValueError("chunked response body ended early")
                buffer.extend(part)
            if buffer[size : size + 2] != b"\r\n":
                raise ValueError("HTTP chunk lacks a terminator")
            decoded.extend(buffer[:size])
            del buffer[: size + 2]


class GroundhogProcess:
    """A disposable deployment served by an external Groundhog binary."""

    def __init__(
        self,
        binary: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str] | None = None,
        startup_timeout: float = 15.0,
        backend: BackendOptions | None = None,
    ) -> None:
        self.binary = Path(binary).resolve()
        self._owns_root = root is None
        self.root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="groundhog-verify-"))
        self.startup_timeout = startup_timeout
        self.backend = backend or BackendOptions()
        self.backend.validate()
        self.config_path = self.root / "groundhog.toml"
        self.socket_path = self.root / "data" / "ground.sock"
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def client(self) -> UnixHttpClient:
        return UnixHttpClient(self.socket_path)

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                str(self.binary),
                "init",
                str(self.root),
                *self.backend.init_arguments(self.root),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"groundhog init failed ({completed.returncode}): {stderr}")

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("groundhog process is already started")
        if not self.config_path.exists():
            self.initialize()
        self.process = subprocess.Popen(
            [str(self.binary), "serve", "--config", str(self.config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            return_code = self.process.poll()
            if return_code is not None:
                stderr = b"" if self.process.stderr is None else self.process.stderr.read()
                message = stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"groundhog serve failed ({return_code}): {message}")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.1)
                    probe.connect(str(self.socket_path))
                return
            except OSError:
                time.sleep(0.02)
        self.stop()
        raise RuntimeError(f"groundhog socket did not start: {self.socket_path}")

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stderr is not None:
            process.stderr.close()

    def reset_local_state(self) -> None:
        """Delete all local files and reattach to the same remote test prefix."""
        if self.backend.name != "s3":
            raise RuntimeError("local-state-loss reset requires the S3 backend")
        self.stop()
        shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.initialize()
        self.start()

    def close(self) -> None:
        self.stop()
        if self._owns_root:
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> GroundhogProcess:
        try:
            self.start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

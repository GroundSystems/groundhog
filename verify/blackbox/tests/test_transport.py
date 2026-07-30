from __future__ import annotations

import socket
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from verify.blackbox.transport import GroundhogProcess, TransportError, UnixHttpClient


class FailingSocket:
    def __enter__(self) -> FailingSocket:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def settimeout(self, timeout: float) -> None:
        pass

    def connect(self, path: str) -> None:
        pass

    def sendall(self, wire: bytes) -> None:
        raise OSError("write failed")


class TransportTest(unittest.TestCase):
    def test_failed_process_entry_removes_owned_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "owned-root"
            with patch("verify.blackbox.transport.tempfile.mkdtemp", return_value=str(root)):
                process = GroundhogProcess(Path(directory) / "missing-groundhog")
            root.mkdir()
            child = MagicMock()
            child.poll.return_value = 1
            process.process = child
            with patch.object(process, "start", side_effect=RuntimeError("failed")):
                with self.assertRaises(RuntimeError):
                    process.__enter__()
            self.assertFalse(root.exists())
            self.assertIsNone(process.process)
            child.stderr.close.assert_called_once_with()

    def test_send_failure_has_an_unknown_outcome(self) -> None:
        client = UnixHttpClient("unused")
        with patch("verify.blackbox.transport.socket.socket", return_value=FailingSocket()):
            with self.assertRaises(TransportError) as caught:
                client.request("POST", "/v1/events", body=b"{}")
        self.assertTrue(caught.exception.outcome_unknown)

    def test_content_length_response_over_unix_socket(self) -> None:
        client_stream, server_stream = socket.socketpair()

        def serve() -> None:
            with server_stream:
                server_stream.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n"
                    b"Content-Type: application/json\r\n\r\n"
                    b'{"ok":true}'
                )

        thread = threading.Thread(target=serve)
        thread.start()
        with client_stream:
            response = UnixHttpClient("unused")._read_response(client_stream)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()

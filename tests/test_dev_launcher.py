"""Development launcher checks that do not start the application or use its DB."""

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import dev


class BackendReadinessTests(unittest.TestCase):
    def test_existing_listener_is_rejected_without_stopping_it(self):
        with socket.socket() as listener:
            if os.name != "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, str(port)):
                dev.ensure_ports_available((port,))
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass

    @unittest.skipIf(os.name == "nt", "Checks POSIX reuse of recently closed sockets")
    def test_recently_closed_http_connection_allows_immediate_restart(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
                with listener.accept()[0] as peer:
                    peer.settimeout(1)
                    peer.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
                    client.shutdown(socket.SHUT_WR)
                    self.assertEqual(peer.recv(1), b"")
        dev.ensure_ports_available((port,))

    def test_waits_for_valid_http_response_without_using_proxy(self):
        replies = [
            (503, b'{"detail":"starting"}'),
            (200, b'<html>not the API</html>'),
            (200, b'{"initialized":false}'),
            (200, b'{"code":0,"success":false,"data":{"initialized":false}}'),
            (200, b'{"code":1,"success":true,"data":{"initialized":false}}'),
            (200, b'{"code":0,"success":true,"data":{"initialized":"false"}}'),
            (200, b'{"code":0,"success":true,"data":{"initialized":false}}'),
        ]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = replies.pop(0)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.dict(os.environ, {
                    "http_proxy": "http://127.0.0.1:1",
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "no_proxy": "",
                    "NO_PROXY": "",
                }):
                    dev.wait_for_backend(
                        Mock(poll=Mock(return_value=None)),
                        timeout=5,
                        url=f"http://127.0.0.1:{server.server_port}/api/auth/status",
                    )
                self.assertEqual(replies, [])
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_backend_exit_fails_without_waiting_for_timeout(self):
        with self.assertRaisesRegex(RuntimeError, "状态码 2"):
            dev.wait_for_backend(Mock(poll=Mock(return_value=2)))

    def test_unreachable_backend_times_out_with_diagnostic(self):
        with (
            patch.object(dev, "build_opener") as opener,
            patch.object(dev.time, "monotonic", side_effect=[0, 0, 1, 2]),
            patch.object(dev.time, "sleep"),
        ):
            opener.return_value.open.side_effect = ConnectionRefusedError
            with self.assertRaisesRegex(RuntimeError, "超时.*make dev-api"):
                dev.wait_for_backend(Mock(poll=Mock(return_value=None)), timeout=2)


class LauncherTests(unittest.TestCase):
    def run_launcher(self, wait=None, statuses=(None, 0)):
        backend = Mock(poll=Mock(side_effect=statuses))
        frontend = Mock(poll=Mock(return_value=None))
        events = []

        def launch(command, **options):
            events.append(command)
            return backend if command[-1] == "dev-api" else frontend

        def ready(process):
            self.assertIs(process, backend)
            # No frontend process may be launched before readiness succeeds.
            self.assertEqual(events, [["custom-make", "dev-api"]])
            if wait:
                raise wait
            events.append("ready")

        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(dev.sys, "argv", ["dev.py", "custom-make"]))
            stack.enter_context(patch.object(dev.signal, "signal"))
            stack.enter_context(patch.object(dev, "ensure_ports_available"))
            stack.enter_context(patch.object(dev.subprocess, "Popen", side_effect=launch))
            stack.enter_context(patch.object(dev, "wait_for_backend", side_effect=ready))
            stack.enter_context(patch.object(dev.time, "sleep"))
            cleanup = stack.enter_context(patch.object(dev, "stop_processes"))
            result = dev.main()
        return result, events, cleanup, backend, frontend

    def test_frontend_starts_after_readiness_and_both_are_cleaned_up(self):
        result, events, cleanup, backend, frontend = self.run_launcher()
        self.assertEqual(result, 1)
        self.assertEqual(events, [
            ["custom-make", "dev-api"], "ready", ["custom-make", "dev-web"],
        ])
        cleanup.assert_called_once_with([backend, frontend])

    def test_backend_failure_does_not_start_frontend(self):
        result, events, cleanup, backend, _ = self.run_launcher(wait=RuntimeError("failed"))
        self.assertEqual(result, 1)
        self.assertEqual(events, [["custom-make", "dev-api"]])
        cleanup.assert_called_once_with([backend])

    def test_ctrl_c_while_waiting_cleans_up_backend(self):
        result, events, cleanup, backend, _ = self.run_launcher(wait=KeyboardInterrupt())
        self.assertEqual(result, 0)
        self.assertEqual(events, [["custom-make", "dev-api"]])
        cleanup.assert_called_once_with([backend])

    def test_occupied_port_aborts_before_starting_any_children(self):
        with (
            patch.object(dev.signal, "signal"),
            patch.object(dev, "ensure_ports_available", side_effect=RuntimeError("occupied")),
            patch.object(dev.subprocess, "Popen") as launch,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(dev.main(), 1)
        launch.assert_not_called()


@unittest.skipIf(os.name == "nt", "POSIX process-group cleanup")
class ProcessCleanupTests(unittest.TestCase):
    def test_cleans_descendants_with_live_or_exited_group_leader(self):
        for parent_exits in (False, True):
            with self.subTest(parent_exits=parent_exits), tempfile.TemporaryDirectory() as directory:
                pid_file = Path(directory) / "child.pid"
                code = (
                    "import subprocess, sys, time; from pathlib import Path; "
                    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                    "Path(sys.argv[1]).write_text(str(child.pid)); "
                    + ("sys.exit(0)" if parent_exits else "child.wait()")
                )
                parent = subprocess.Popen([sys.executable, "-c", code, str(pid_file)], start_new_session=True)
                try:
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    child_pid = int(pid_file.read_text())
                    if parent_exits:
                        parent.wait(timeout=5)
                    dev.stop_processes([parent])
                    self.assertIsNotNone(parent.poll())
                    while time.monotonic() < deadline:
                        result = subprocess.run(
                            ["ps", "-p", str(child_pid), "-o", "stat="],
                            capture_output=True, text=True, check=False,
                        )
                        # A zombie has exited; its new parent owns reaping it.
                        if not result.stdout.strip() or result.stdout.lstrip().startswith("Z"):
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("Owned descendant survived process-group cleanup")
                finally:
                    dev.stop_processes([parent])


if __name__ == "__main__":
    unittest.main()

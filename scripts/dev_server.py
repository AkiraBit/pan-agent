"""Bounded, signal-safe reload supervision for local development only."""

import logging
import time
from pathlib import Path

import uvicorn
from uvicorn.supervisors.basereload import BaseReload

logger = logging.getLogger("uvicorn.error")
ROOT = Path(__file__).resolve().parents[1]


class DevelopmentReload(BaseReload):
    def __init__(self, config, target, sockets, *, watch_roots, stop_timeout=10):
        super().__init__(config, target, sockets)
        self.reloader_name = "PanWatchReload"
        self.watch_roots = tuple(Path(path) for path in watch_roots)
        self.stop_timeout = stop_timeout
        self.exit_code = 0
        self._stopping = False
        self._files = self.snapshot()

    def signal_handler(self, sig, frame):
        # Python signal handlers may re-enter one another. Event.set() acquires
        # a non-reentrant lock and can deadlock under repeated SIGINT/SIGTERM.
        # Only update a flag here; all cleanup happens in the normal loop.
        self._stopping = True

    def snapshot(self):
        files = {}
        for root in self.watch_roots:
            candidates = (root,) if root.suffix == ".py" else root.rglob("*.py")
            for path in candidates:
                if any(part in {".venv", "venv", "node_modules", "__pycache__", ".git"} for part in path.parts):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files[path] = (stat.st_mtime_ns, stat.st_size)
        return files

    def should_restart(self):
        if self._stopping:
            raise StopIteration
        time.sleep(self.config.reload_delay)
        if self._stopping:
            raise StopIteration
        if not self.process.is_alive():
            self.exit_code = 1
            logger.error("Development worker exited (%s); releasing the listening port.", self.process.exitcode)
            raise StopIteration
        current = self.snapshot()
        changes = [path for path in self._files.keys() | current.keys() if self._files.get(path) != current.get(path)]
        self._files = current
        return changes or None

    def stop_worker(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=self.stop_timeout)
        if self.process.is_alive():
            logger.warning("Development worker did not stop within %ss; forcing exit.", self.stop_timeout)
            self.process.kill()
            self.process.join(timeout=self.stop_timeout)
        if self.process.is_alive():
            raise RuntimeError("Development worker could not be stopped")

    def restart(self):
        from uvicorn._subprocess import get_subprocess

        self.stop_worker()
        if not self._stopping:
            self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
            self.process.start()

    def shutdown(self):
        try:
            self.stop_worker()
        finally:
            for sock in self.sockets:
                sock.close()
        logger.info("Stopped development reloader [%s]", self.pid)


def run_development_server(*, app="server:app", host="0.0.0.0", port=8000, watch_roots=None, stop_timeout=10):
    roots = watch_roots if watch_roots is not None else (ROOT / "server.py", ROOT / "src", ROOT / "packages")
    config = uvicorn.Config(
        app, host=host, port=port, reload=True, reload_delay=0.5,
        reload_dirs=[str(path) for path in roots if Path(path).is_dir()],
        timeout_graceful_shutdown=8,
    )
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    supervisor = DevelopmentReload(config, server.run, [sock], watch_roots=roots, stop_timeout=stop_timeout)
    try:
        supervisor.run()
    finally:
        # Also release the port when startup or the watcher itself fails.
        if hasattr(supervisor, "process") and supervisor.process.is_alive():
            supervisor.shutdown()
        sock.close()
    return supervisor.exit_code


if __name__ == "__main__":
    raise SystemExit(run_development_server())

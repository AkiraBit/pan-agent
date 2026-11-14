"""Real development supervisor checks with an isolated ASGI app, never the user DB."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest

from scripts.dev_server import DevelopmentReload

ROOT = Path(__file__).resolve().parents[1]
OPENER = build_opener(ProxyHandler({}))
APP = '''import json, os, time
VERSION = {version!r}
async def app(scope, receive, send):
    if scope['type'] == 'lifespan':
        while True:
            event = await receive()
            if event['type'] == 'lifespan.startup':
                await send({{'type':'lifespan.startup.complete'}})
            elif event['type'] == 'lifespan.shutdown':
                if os.environ.get('TEST_STUCK_SHUTDOWN') == '1':
                    time.sleep(60)
                await send({{'type':'lifespan.shutdown.complete'}})
                return
    else:
        await send({{'type':'http.response.start','status':200,'headers':[]}})
        await send({{'type':'http.response.body','body':json.dumps({{'pid':os.getpid(),'version':VERSION}}).encode()}})
'''


@pytest.fixture
def dev_server(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    app_file = source / 'test_app.py'
    app_file.write_text(APP.format(version='before'))
    runner = tmp_path / 'run.py'
    runner.write_text(
        'from scripts.dev_server import run_development_server\n'
        "if __name__ == '__main__':\n"
        f"    raise SystemExit(run_development_server(app='test_app:app', host='127.0.0.1', "
        f"port=int(__import__('sys').argv[1]), watch_roots=[{str(source)!r}], stop_timeout=0.5))\n"
    )
    processes = []

    def start(stuck=False):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join((str(ROOT), str(source)))
        env['TEST_STUCK_SHUTDOWN'] = '1' if stuck else '0'
        log = (tmp_path / f'{port}.log').open('w')
        process = subprocess.Popen([sys.executable, str(runner), str(port)], cwd=tmp_path, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append((process, log))
        return process, port

    yield start, app_file, tmp_path
    for process, log in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        log.close()


def response(port, *, predicate=lambda body: True, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with OPENER.open(f'http://127.0.0.1:{port}/', timeout=0.3) as request:
                body = json.load(request)
                if predicate(body):
                    return body
        except (OSError, URLError, ValueError):
            pass
        time.sleep(0.05)
    pytest.fail('Development worker did not serve the expected response')


def assert_released(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', port))


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process signals')
def test_reload_tracks_source_additions_deletions_and_ignores_reports(dev_server):
    start, app_file, directory = dev_server
    process, port = start()
    before = response(port)
    (directory / 'report.py').write_text('not source')
    time.sleep(1.1)
    assert response(port)['pid'] == before['pid']
    app_file.write_text(APP.format(version='after-change'))
    changed = response(port, predicate=lambda body: body['version'] == 'after-change')
    extra = app_file.parent / 'new_module.py'
    extra.write_text('VALUE = 1\n')
    added = response(port, predicate=lambda body: body['pid'] != changed['pid'])
    extra.unlink()
    response(port, predicate=lambda body: body['pid'] != added['pid'])
    assert process.poll() is None


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process signals')
def test_worker_crash_exits_supervisor_and_releases_port(dev_server):
    start, _, _ = dev_server
    process, port = start()
    child = response(port)
    os.kill(child['pid'], signal.SIGKILL)
    assert process.wait(timeout=5) == 1
    assert_released(port)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process signals')
def test_repeated_stop_signals_bound_stuck_shutdown_and_release_port(dev_server):
    start, _, _ = dev_server
    process, port = start(stuck=True)
    response(port)
    for _ in range(25):
        if process.poll() is not None:
            break
        process.send_signal(signal.SIGTERM)
        time.sleep(0.005)
    assert process.wait(timeout=5) == 0
    assert_released(port)


def test_signal_handler_does_not_acquire_event_lock():
    # Re-entering threading.Event.set while its Condition lock is held caused
    # the observed supervisor deadlock. The handler must remain lock-free.
    supervisor = object.__new__(DevelopmentReload)
    import threading
    supervisor.should_exit = threading.Event()
    acquired = []
    supervisor.should_exit.set = lambda: acquired.append(True)
    supervisor.signal_handler(signal.SIGTERM, None)
    supervisor.signal_handler(signal.SIGTERM, None)
    assert supervisor._stopping
    assert not acquired

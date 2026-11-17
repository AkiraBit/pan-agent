"""Run both development servers and stop their process trees together."""

import errno
import json
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


BACKEND_URL = "http://127.0.0.1:8000/api/auth/status"


def ensure_ports_available(ports=(8000, 5183)):
    """Reject existing listeners without treating recently closed sockets as busy."""
    for port in ports:
        # BSD permits wildcard and loopback listeners to share a port with
        # SO_REUSEADDR, so probe them separately to catch a live local service.
        for family, host in (
            (socket.AF_INET, "0.0.0.0"), (socket.AF_INET, "127.0.0.1"),
            (socket.AF_INET6, "::"), (socket.AF_INET6, "::1"),
        ):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    if family == socket.AF_INET6:
                        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    if os.name != "nt":
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind((host, port))
                    probe.listen(1)
            except OSError as error:
                if family == socket.AF_INET6 and error.errno in (
                    errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL, errno.ENOPROTOOPT,
                ):
                    continue
                raise RuntimeError(
                    f"开发端口 {port} 不可用，请先停止占用该端口的服务后重试。"
                ) from error


def wait_for_backend(process, timeout=600, url=BACKEND_URL):
    """Wait for an HTTP response after dependency installation and app startup."""
    # Local readiness must not depend on the user's HTTP_PROXY configuration.
    opener = build_opener(ProxyHandler({}))
    started = time.monotonic()
    next_notice = started + 15
    while time.monotonic() - started < timeout:
        status = process.poll()
        if status is not None:
            raise RuntimeError(f"dev-api 已退出（状态码 {status}），请检查上方后端日志。")
        try:
            with opener.open(url, timeout=1) as response:
                body = json.load(response)
                # Public API responses are wrapped by the application's
                # response middleware, including /api/auth/status.
                payload = body.get("data") if isinstance(body, dict) and body.get("success") is True and body.get("code") == 0 else None
                if (
                    response.status == 200
                    and isinstance(payload, dict)
                    and isinstance(payload.get("initialized"), bool)
                ):
                    return
        except (OSError, URLError, ValueError):
            pass
        now = time.monotonic()
        if now >= next_notice:
            print(f"后端仍在准备中（已等待 {int(now - started)} 秒），就绪后将自动启动前端…", flush=True)
            next_notice = now + 15
        time.sleep(0.2)
    raise RuntimeError(
        f"等待后端就绪超时（{timeout} 秒）：{url} 未正常响应。"
        "请检查上方依赖安装/后端启动日志，或单独运行 make dev-api 排查。"
    )


def stop_processes(processes):
    if os.name == "nt":
        for process in processes:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for process in processes:
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # On macOS a process group that has already disappeared
                    # can report EPERM instead of ESRCH.
                    if process.poll() is None:
                        raise
            if sig == signal.SIGTERM:
                for process in processes:
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
    for process in processes:
        process.wait()


def main():
    make = sys.argv[1] if len(sys.argv) > 1 else "make"
    processes = []
    if os.name != "nt":
        def interrupt_on_termination(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupt_on_termination)
    try:
        ensure_ports_available()
        print("正在准备后端 :8000（首次安装依赖可能需要数分钟）；按 Ctrl+C 停止。", flush=True)
        for target in ("dev-api", "dev-web"):
            options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            processes.append(subprocess.Popen([make, target], **options))
            if target == "dev-api":
                wait_for_backend(processes[-1])
                print("后端已就绪，正在启动前端 http://localhost:5183 …", flush=True)
        while True:
            for target, process in zip(("dev-api", "dev-web"), processes):
                status = process.poll()
                if status is not None:
                    print(f"{target} 已退出（状态码 {status}），正在停止其他服务。", flush=True)
                    return status if status > 0 else 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n正在停止开发服务…", flush=True)
        return 0
    except (OSError, RuntimeError) as error:
        print(f"开发服务启动失败：{error}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    sys.exit(main())

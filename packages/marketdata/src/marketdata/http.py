"""统一 HTTP 工具:走系统代理(trust_env=True)+ 按 host 节流 + 退避重试 + 来源标记。

默认 trust_env=True —— 遵循进程 env 的 HTTP_PROXY/NO_PROXY(宿主按 UI 的 http_proxy 设置统一注入);
没配代理时即直连。个别调用可用 proxy= 显式覆盖。
"""

from __future__ import annotations

import contextvars
import logging
import random
import threading
import time
from contextlib import contextmanager
from typing import Any

import httpx
from marketdata.fallback import SourceFailure

logger = logging.getLogger(__name__)

_FETCH_SOURCE: contextvars.ContextVar[str] = contextvars.ContextVar("fetch_source", default="")
_ATTEMPT_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("md_attempt_deadline", default=None)


@contextmanager
def attempt_budget(seconds: float):
    previous = _ATTEMPT_DEADLINE.get()
    deadline = time.monotonic() + seconds
    token = _ATTEMPT_DEADLINE.set(min(previous, deadline) if previous is not None else deadline)
    try:
        yield
    finally:
        _ATTEMPT_DEADLINE.reset(token)


def within_budget(timeout: float) -> float:
    deadline = _ATTEMPT_DEADLINE.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceFailure("market-data attempt budget exhausted")
    return min(timeout, remaining)


@contextmanager
def fetch_source(name: str):
    """标注取数来源,写入失败日志便于定位触发方。"""
    token = _FETCH_SOURCE.set(name or "")
    try:
        yield
    finally:
        _FETCH_SOURCE.reset(token)


def source_suffix() -> str:
    src = _FETCH_SOURCE.get()
    return f" [src={src}]" if src else ""


# 失败原因收集:默认 None = 不收集(生产热路径零开销)。数据源"测试"按钮用 capture_errors()
# 包住取数调用,把 market_get / vendor 的真实失败原因收上来透到 UI,而不是只显示"无数据"。
_ERROR_SINK: contextvars.ContextVar[list | None] = contextvars.ContextVar("md_error_sink", default=None)


@contextmanager
def capture_errors():
    """进入后,market_get / record_error 的失败原因会被收集到 yield 出的 list。"""
    errs: list[str] = []
    token = _ERROR_SINK.set(errs)
    try:
        yield errs
    finally:
        _ERROR_SINK.reset(token)


def record_error(msg: str) -> None:
    """把一条失败原因写入当前 capture_errors 上下文(无上下文则忽略)。
    供适配器捕获异常时上报原始错误。"""
    sink = _ERROR_SINK.get()
    if sink is not None and msg:
        sink.append(msg)


_THROTTLE_LOCK = threading.Lock()
_last_call: dict[str, float] = {}


def throttle(host_key: str, min_interval_s: float, *, deadline: float | None = None) -> None:
    """保证对同一 host 的请求间隔 ≥ min_interval_s。"""
    if min_interval_s <= 0:
        return
    with _THROTTLE_LOCK:
        now = time.time()
        scheduled = max(now, _last_call.get(host_key, 0.0) + min_interval_s)
        if deadline is not None and scheduled - now >= deadline - time.monotonic():
            raise TimeoutError("market-data throttle budget exhausted")
        _last_call[host_key] = scheduled
    wait = scheduled - now
    if wait > 0:
        time.sleep(wait)


def market_get(
    url: str,
    *,
    host_key: str,
    params: dict | None = None,
    headers: dict | None = None,
    min_interval_s: float = 0.0,
    timeout: float = 10.0,
    retries: int = 2,
    total_timeout: float = 20.0,
    backoff: float = 0.4,
    jitter: float = 0.25,
    parse: str = "text",   # "text" | "json" | "content"
    encoding: str | None = None,
    symbol: str = "",
    log_label: str = "",
    raise_for_status: bool = True,
    trust_env: bool = True,
    follow_redirects: bool = True,
    verify: bool = True,
    proxy: str | None = None,
) -> Any | None:
    """走系统代理(env)+ 按 host 节流 + 退避重试。成功返回解析结果,失败返回 None 并打带来源日志。

    proxy: 显式代理,仅在给了值时传给 httpx.Client 覆盖 env 代理;不传则遵循 trust_env(env)。
    """
    effective_proxy = proxy
    last_err: Any = None
    attempt_deadline = _ATTEMPT_DEADLINE.get()
    deadline = time.monotonic() + max(0.0, total_timeout)
    if attempt_deadline is not None:
        deadline = min(deadline, attempt_deadline)
    for attempt in range(max(1, retries + 1)):
        if time.monotonic() >= deadline:
            last_err = TimeoutError("market-data retry budget exhausted")
            break
        try:
            throttle(host_key, min_interval_s, deadline=deadline)
        except TimeoutError as exc:
            last_err = exc
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            last_err = TimeoutError("market-data retry budget exhausted")
            break
        try:
            with httpx.Client(
                follow_redirects=follow_redirects,
                timeout=min(timeout, remaining),
                headers=headers,
                trust_env=trust_env,
                verify=verify,
                **({"proxy": effective_proxy} if effective_proxy else {}),
            ) as client:
                resp = client.get(url, params=params)
                if raise_for_status:
                    resp.raise_for_status()
                if parse == "json":
                    return resp.json()
                if parse == "content":
                    return resp.content
                if encoding:
                    return resp.content.decode(encoding, errors="ignore")
                return resp.text
        except httpx.HTTPStatusError as exc:
            last_err = exc
            if attempt_deadline is not None and exc.response.status_code in (401, 403, 429):
                status = exc.response.status_code
                raw = exc.response.headers.get("Retry-After", "")
                delay = min(int(raw), 600) if raw.isascii() and raw.isdigit() and len(raw) <= 8 else (30 if status == 429 else 60)
                raise SourceFailure(f"{host_key}: HTTP {status}", retry_after=delay) from None
        except Exception as e:
            last_err = e
        if attempt < retries:
            delay = min(backoff * (attempt + 1) + random.uniform(0, jitter),
                        max(0.0, deadline - time.monotonic()))
            if delay > 0:
                time.sleep(delay)

    if last_err is not None:
        label = log_label or host_key
        sym = f" symbol={symbol}" if symbol else ""
        logger.warning(f"{label} 获取失败{sym}: {last_err}{source_suffix()}")
        record_error(f"{label}{sym}: {type(last_err).__name__}: {last_err}")
    return None

"""Calls the engines with timeout, retry and backoff. A failing engine never fails the whole check."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .config import Settings

log = logging.getLogger("shinri.engines")


class EngineClient:
    def __init__(self, settings: Settings, engine_app: Any = None):
        self.s = settings
        # In-process engines are called through ASGI, no network port needed.
        self._inproc = httpx.ASGITransport(app=engine_app) if engine_app is not None else None

    def _client(self, url: str) -> httpx.AsyncClient:
        if urlparse(url).hostname == "inproc":
            if self._inproc is None:
                raise RuntimeError("in-process engines requested but no engine app was provided")
            return httpx.AsyncClient(transport=self._inproc, timeout=self.s.engine_timeout)
        return httpx.AsyncClient(timeout=self.s.engine_timeout)

    async def call(self, engine: str, payload: dict) -> tuple[Optional[dict], dict]:
        """Returns (json_or_None, run_info). run_info.status: ok | skipped | failed."""
        url = self.s.engine_url(engine)
        run: dict = {"engine": engine, "status": "failed", "mock": False, "ms": 0, "attempts": 0, "error": None, "notes": []}
        t0 = time.monotonic()
        last_err = "unknown error"
        for attempt in range(1, self.s.engine_attempts + 1):
            run["attempts"] = attempt
            try:
                async with self._client(url) as c:
                    r = await c.post(url, json=payload)
                if r.status_code == 501:
                    run.update(status="skipped", error="not implemented yet")
                    break
                if 400 <= r.status_code < 500:
                    last_err = f"engine rejected the request (HTTP {r.status_code})"
                    break                                   # our fault, retrying will not help
                if r.status_code >= 500:
                    last_err = f"engine error (HTTP {r.status_code})"
                else:
                    data = r.json()
                    run.update(status="ok", error=None, mock=bool(data.get("mock")))
                    run["ms"] = int((time.monotonic() - t0) * 1000)
                    return data, run
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = f"{type(e).__name__}: engine unreachable or too slow"
            except ValueError:
                last_err = "engine returned invalid JSON"
            except Exception as e:  # noqa: BLE001 - an engine bug must not crash the pipeline
                last_err = f"{type(e).__name__}"
                log.exception("engine %s crashed the client", engine)
            if attempt < self.s.engine_attempts:
                await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 4.0))
        else:
            run["error"] = last_err
        if run["status"] == "failed" and not run["error"]:
            run["error"] = last_err
        run["ms"] = int((time.monotonic() - t0) * 1000)
        log.warning("engine %s %s: %s", engine, run["status"], run["error"])
        return None, run

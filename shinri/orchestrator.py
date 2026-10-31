"""Runs one check end to end: claim+media in parallel, then origin, then verdict."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from pydantic import ValidationError

from . import fusion
from .config import Settings
from .db import DB
from .engine_client import EngineClient
from .models import Claim, EngineResult, Signal, VerdictResult

log = logging.getLogger("shinri.orchestrator")
Notifier = Callable[[dict], Awaitable[None]]


class Orchestrator:
    def __init__(self, settings: Settings, db: DB, engines: EngineClient):
        self.s, self.db, self.engines = settings, db, engines
        self.notifiers: dict[str, Notifier] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_checks)
        self._tasks: set[asyncio.Task] = set()

    def submit(self, check_id: str) -> None:
        t = asyncio.get_running_loop().create_task(self._guarded(check_id))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def wait_all(self) -> None:           # used by tests
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _guarded(self, cid: str) -> None:
        async with self._sem:
            try:
                await asyncio.wait_for(self._run(cid), self.s.check_timeout)
            except asyncio.TimeoutError:
                self.db.set_status(cid, "failed", "The check took too long and was stopped. Please try again.")
            except Exception:  # noqa: BLE001
                log.exception("check %s crashed", cid)
                self.db.set_status(cid, "failed", "Something went wrong while checking. Please try again.")
        await self._notify(cid)

    async def _notify(self, cid: str) -> None:
        rec = self.db.get_record(cid)
        fn = self.notifiers.get(rec["channel"]) if rec else None
        if fn:
            try:
                await fn(rec)
            except Exception:  # noqa: BLE001
                log.exception("notifier for %s failed", cid)

    # ------------------------------------------------------------------
    def _payload(self, cid: str) -> dict:
        rec = self.db.get_record(cid)
        mp = self.db.media_path(cid)
        rec["mediaPath"] = mp[0] if mp else None
        rec["mediaUrl"] = f"/media/{cid}" if mp else None
        return rec

    def _ingest(self, cid: str, engine: str, data: Optional[dict], run: dict) -> None:
        notes: list[str] = []
        if data is not None:
            try:
                res = EngineResult.model_validate(data)
            except ValidationError:
                run.update(status="failed", error="engine response did not match the contract")
                self.db.add_engine_run(cid, run)
                return
            good, dropped = [], 0
            for raw in res.signals:
                try:
                    sig = Signal.model_validate({**raw, "engine": engine if engine in ("claim", "media", "origin") else raw.get("engine")})
                    d = sig.model_dump()
                    d["mock"] = d["mock"] or res.mock
                    good.append(d)
                except ValidationError:
                    dropped += 1
            if dropped:
                notes.append(f"{dropped} malformed signal(s) from the {engine} engine were ignored.")
            if good:
                self.db.add_signals(cid, good)
            if res.claims:
                self.db.save_claims(cid, [c.model_dump() for c in res.claims])
            self.db.set_text_fields(cid, res.language, res.transcript)
            notes += res.notes
        run["notes"] = notes
        self.db.add_engine_run(cid, run)

    async def _run(self, cid: str) -> None:
        self.db.set_status(cid, "processing")
        rec = self._payload(cid)
        has_media = rec["input"]["type"] in ("image", "video", "audio")

        # Stage 1: claim and media in parallel
        jobs = [self.engines.call("claim", rec)]
        if has_media:
            jobs.append(self.engines.call("media", rec))
        results = await asyncio.gather(*jobs)
        names = ["claim"] + (["media"] if has_media else [])
        for name, (data, run) in zip(names, results):
            self._ingest(cid, name, data, run)
        if not has_media:
            self.db.add_engine_run(cid, {"engine": "media", "status": "skipped", "notes": ["No media in this check."]})

        # Stage 2: origin (can use the extracted claims)
        data, run = await self.engines.call("origin", self._payload(cid))
        self._ingest(cid, "origin", data, run)

        # Stage 3: verdict
        rec = self._payload(cid)
        data, run = await self.engines.call("verdict", rec)
        used = "engine"
        verdict = explanation = None
        if data is not None:
            try:
                vr = VerdictResult.model_validate(data)
                verdict, explanation = vr.verdict.model_dump(), vr.explanation.model_dump()
                run["mock"] = vr.mock
            except ValidationError:
                run.update(status="failed", error="verdict response did not match the contract")
        if verdict is None:
            used = "platform-fallback"
            verdict = fusion.fuse(rec["signals"])
            notes = []
            failed = [r["engine"] for r in rec["engineRuns"] if r["status"] == "failed"]
            if failed:
                notes.append("These checks could not run: " + ", ".join(failed) + ".")
            explanation = fusion.template_explanation(verdict, notes)
            if run["status"] == "failed":
                run["notes"].append("Verdict engine failed; the platform's reference fusion was used.")
        self.db.add_engine_run(cid, run)
        self.db.save_verdict(cid, verdict, explanation, used)
        self.db.set_status(cid, "done")

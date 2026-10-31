"""FastAPI app: shared-contract endpoints, in-process engine routers, web UI."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .db import DB
from .engine_client import EngineClient
from .engines import claim as e_claim, media as e_media, origin as e_origin, verdict as e_verdict
from .orchestrator import Orchestrator
from .service import CheckService
from .telegram_bot import TelegramBot
from .validation import InputError, largest_allowed

log = logging.getLogger("shinri.api")
STATIC = os.path.join(os.path.dirname(__file__), "static")


def create_app(settings: Optional[Settings] = None, engine_app=None) -> FastAPI:
    s = settings or Settings.from_env()
    db = DB(s.db_path)
    hits: dict[str, deque] = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stale = db.fail_stale(older_than_s=0)
        if stale:
            log.warning("marked %d unfinished checks as failed after restart", stale)
        bot_task = None
        if s.telegram_token:
            bot = TelegramBot(s, app.state.service)
            app.state.bot = bot
            app.state.orch.notifiers["telegram"] = bot.notify_done
            bot_task = asyncio.create_task(bot.run())
            log.info("Telegram tipline started")
        yield
        if bot_task:
            app.state.bot.stop()
            bot_task.cancel()

    app = FastAPI(title="Shinri AI", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.db = s, db
    app.state.engines = EngineClient(s, engine_app=engine_app or app)
    app.state.orch = Orchestrator(s, db, app.state.engines)
    app.state.service = CheckService(s, db, app.state.orch)

    for r in (e_claim.router, e_media.router, e_origin.router, e_verdict.router):
        app.include_router(r, prefix="/engines", tags=["engines"])

    def limited(request: Request) -> bool:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))
        q, now = hits[ip], time.monotonic()
        while q and now - q[0] > s.rate_limit_window_s:
            q.popleft()
        if len(q) >= s.rate_limit_per_window:
            return True
        q.append(now)
        return False

    @app.exception_handler(InputError)
    async def input_error(_: Request, e: InputError):
        return JSONResponse({"error": e.message}, status_code=e.status)

    @app.get("/health")
    async def health():
        urls = {n: ("in-process" if "inproc" in s.engine_url(n) else "remote") for n in ("claim", "media", "origin", "verdict")}
        return {"ok": True, "version": __version__, "telegram": bool(s.telegram_token), "engines": urls}

    @app.post("/checks", status_code=202)
    async def post_check(request: Request, text: str = Form(""), file: Optional[UploadFile] = File(None)):
        if limited(request):
            raise HTTPException(429, "Too many checks from your connection. Please wait a few minutes.")
        data = None
        if file is not None and file.filename is not None:
            cap = largest_allowed(s) + 1
            data = await file.read(cap)
            if len(data) >= cap:
                raise InputError(f"That file is too large. The biggest allowed is {cap // (1024 * 1024)} MB.", 413)
        return app.state.service.create(text=text, data=data or None, channel="web")

    @app.get("/checks/{check_id}")
    async def get_check(check_id: str):
        rec = db.get_record(check_id)
        if not rec:
            raise HTTPException(404, "No such check.")
        return rec

    @app.get("/checks")
    async def list_checks(limit: int = 20):
        return db.list_checks(max(1, min(limit, 100)))

    @app.get("/media/{check_id}")
    async def get_media(check_id: str):
        m = db.media_path(check_id)
        if not m or not os.path.exists(m[0]):
            raise HTTPException(404, "No media for this check.")
        return FileResponse(m[0], media_type=m[1])

    @app.get("/trending")
    async def trending():
        return {"source": "claims checked more than once on Shinri AI in the last 24 hours",
                "monitors": "not enabled", "items": db.trending()}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    return app

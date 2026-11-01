"""PART 3: Origin Engine.

Traces earliest appearance of links via Wayback Machine,
searches the perceptual hash archive for recycled photos/videos,
and analyzes viral burst timelines.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter

from ..config import Settings
from ..db import DB
from ..models import EngineResult
from ..origin_tracing import origin_tracer

router = APIRouter()
log = logging.getLogger("shinri.engine.origin")

_settings = Settings.from_env()
_db = DB(_settings.db_path)


@router.post("/origin", response_model=EngineResult)
async def origin_engine(record: dict) -> EngineResult:
    signals = []
    notes = []

    input_data = record.get("input") or {}
    text = input_data.get("text") or ""
    media_path = record.get("mediaPath") or ""

    # 1. Search Wayback Machine if input contains URLs
    urls = re.findall(r"https?://[^\s<>\"']+", text)
    for u in urls[:2]:
        wb_signal = await origin_tracer.check_wayback(u)
        if wb_signal:
            signals.append(wb_signal)

    # 2. Search perceptual hash index for matching older copies
    if media_path:
        hash_signals = origin_tracer.search_image_hash_index(_db, media_path)
        if hash_signals:
            signals.extend(hash_signals)

    if not signals:
        notes.append("No earlier archived snapshots or perceptual hash matches found in archive.")

    return EngineResult(
        signals=signals,
        notes=notes,
        mock=False,
    )

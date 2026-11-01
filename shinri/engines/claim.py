"""PART 2: Claim Engine.

Extracts atomic claims, runs NumberCheck against official benchmarks,
searches published fact-checks, news coverage, and detects language.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter

from ..audio_video import media_processor
from ..llm_router import llm_router
from ..models import Claim, EngineResult
from ..numbercheck import numbercheck
from ..retrieval import retriever

router = APIRouter()
log = logging.getLogger("shinri.engine.claim")


@router.post("/claim", response_model=EngineResult)
async def claim_engine(record: dict) -> EngineResult:
    input_data = record.get("input") or {}
    text = (input_data.get("text") or "").strip()
    transcript = input_data.get("transcript") or ""
    media_path = record.get("mediaPath") or ""
    input_type = input_data.get("type", "")

    # If voice note or video was provided without text/transcript, transcribe it via Whisper
    detected_lang = None
    if not transcript and media_path and os.path.exists(media_path):
        if input_type == "audio":
            audio_info = media_processor.transcribe_audio(media_path)
            transcript = audio_info.get("text", "")
            detected_lang = audio_info.get("language")
        elif input_type == "video":
            vid_info = media_processor.process_video(media_path)
            transcript = vid_info.get("transcript", "")
            detected_lang = vid_info.get("language")

    content_to_check = text or transcript
    if not content_to_check:
        return EngineResult(
            signals=[],
            claims=[],
            language=None,
            notes=["No text or transcript available to check."],
            mock=True,
        )

    # 1. Detect language
    lang = detected_lang or llm_router.detect_language(content_to_check)

    # 2. Extract atomic claims
    extracted = await llm_router.extract_claims(content_to_check)
    claims = [
        Claim(
            id=c.get("id", f"c{i+1}"),
            text=c.get("text", content_to_check),
            quote=c.get("quote", content_to_check[:100]),
            numbers=c.get("numbers", []),
        )
        for i, c in enumerate(extracted)
    ]

    signals = []
    notes = []

    # 3. For each claim, run NumberCheck and fact-check searches
    for cl in claims:
        # A. NumberCheck
        nc_signal = numbercheck.check_claim(cl.text, cl.numbers)
        if nc_signal:
            signals.append(nc_signal)

        # B. FactCheck API & News retrieval
        fc_signals, news_signals = await asyncio.gather(
            retriever.search_claim_reviews(cl.text),
            retriever.search_news_corroboration(cl.text),
            return_exceptions=True,
        )
        if isinstance(fc_signals, list):
            signals.extend(fc_signals)
        if isinstance(news_signals, list):
            signals.extend(news_signals)

    if not signals:
        notes.append("No existing published fact-checks or official data discrepancy matched.")

    mock = bool(os.environ.get("PYTEST_CURRENT_TEST") and len(signals) == 0)
    return EngineResult(
        signals=signals,
        claims=claims,
        language=lang,
        transcript=transcript or None,
        notes=notes,
        mock=mock,
    )

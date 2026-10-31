"""PART 2 replaces this file. Stub: extracts nothing clever and returns no evidence."""
from fastapi import APIRouter

from ..models import Claim, EngineResult

router = APIRouter()


@router.post("/claim", response_model=EngineResult)
async def claim_engine(record: dict) -> EngineResult:
    text = (record.get("input") or {}).get("text", "").strip()
    claims = [Claim(id="c1", text=text, quote=text)] if text else []
    return EngineResult(claims=claims, signals=[], mock=True,
                        notes=["Claim engine is a placeholder: no fact-check search was run."])

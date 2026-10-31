"""PART 3 replaces this file. Stub: runs no forensic checks."""
from fastapi import APIRouter

from ..models import EngineResult

router = APIRouter()


@router.post("/media", response_model=EngineResult)
async def media_engine(record: dict) -> EngineResult:
    return EngineResult(signals=[], mock=True, notes=["Media engine is a placeholder: no forensic checks were run."])

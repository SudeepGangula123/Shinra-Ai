"""PART 3 replaces this file. Stub: traces nothing."""
from fastapi import APIRouter

from ..models import EngineResult

router = APIRouter()


@router.post("/origin", response_model=EngineResult)
async def origin_engine(record: dict) -> EngineResult:
    return EngineResult(signals=[], mock=True, notes=["Origin engine is a placeholder: no earlier appearance was searched."])

"""PART 2 replaces this file (Bayesian fusion + cited explanation).

Until it is implemented this returns 501, and the platform falls back to shinri/fusion.py
with a template explanation, marking the result `fusion: platform-fallback`.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/verdict")
async def verdict_engine(record: dict):
    raise HTTPException(status_code=501, detail="verdict engine not implemented yet")

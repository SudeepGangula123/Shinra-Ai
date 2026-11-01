import asyncio
import pytest
from fastapi.testclient import TestClient

from shinri.api import create_app
from shinri.llm_router import llm_router
from tests.conftest import make_settings


def test_language_detection():
    assert llm_router.detect_language("This is an English forward") == "en"
    assert llm_router.detect_language("ఈ వీడియో నిజమైనదా లేదా నకిలీదా?") == "te"  # Telugu
    assert llm_router.detect_language("यह खबर पूरी तरह से फर्जी है") == "hi"  # Hindi
    assert llm_router.detect_language("இந்த செய்தி உண்மையா?") == "ta"  # Tamil
    assert llm_router.detect_language("এই খবরটি ভুয়ো") == "bn"  # Bengali


def test_claim_extraction():
    text = "Government announced 50% discount on electricity. Also petrol prices cut by 15 rupees."
    claims = asyncio.run(llm_router.extract_claims(text))
    assert len(claims) >= 2
    assert any(c["numbers"] for c in claims)


def test_claim_engine_endpoint(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        payload = {
            "checkId": "chk_test1",
            "input": {
                "type": "text",
                "text": "India economic growth rate officially reached 18% this quarter",
            },
        }
        resp = c.post("/engines/claim", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["claims"]) > 0
        assert data["language"] == "en"
        # NumberCheck should have flagged this discrepancy
        assert any(s["kind"] == "numbercheck" for s in data["signals"])

import pytest
from fastapi.testclient import TestClient

from shinri.api import create_app
from tests.conftest import JPEG, MP4, OGG, fake_engines, make_settings, wait_done


def post(c, text="", file=None, name="f.bin"):
    return c.post("/checks", data={"text": text}, files={"file": (name, file)} if file else None)


def test_health_and_index(stub_client):
    assert stub_client.get("/health").json()["ok"] is True
    assert "Shinri" in stub_client.get("/").text


def test_text_check_with_stub_engines_is_honest(stub_client):
    r = post(stub_client, "The moon is made of cheese")
    assert r.status_code == 202
    rec = wait_done(stub_client, r.json()["checkId"])
    assert rec["status"] == "done"
    assert rec["verdict"]["label"] == "not_enough_evidence"          # stubs found nothing: no guessing
    assert rec["verdict"]["fusion"] == "platform-fallback"
    assert rec["claims"][0]["quote"] == "The moon is made of cheese"
    runs = {x["engine"]: x for x in rec["engineRuns"]}
    assert runs["claim"]["mock"] and runs["media"]["status"] == "skipped" and runs["verdict"]["status"] == "skipped"
    assert rec["completedAt"] and rec["input"]["type"] == "text"


def test_link_is_classified(stub_client):
    rec = wait_done(stub_client, post(stub_client, "https://example.com/story").json()["checkId"])
    assert rec["input"]["type"] == "link"


@pytest.mark.parametrize("blob,kind", [(JPEG, "image"), (MP4, "video"), (OGG, "audio")])
def test_media_checks_call_media_engine_and_store_file(stub_client, blob, kind):
    r = post(stub_client, "caption", blob, "whatever.bin")
    assert r.status_code == 202 and r.json()["inputType"] == kind
    rec = wait_done(stub_client, r.json()["checkId"])
    assert {x["engine"] for x in rec["engineRuns"]} >= {"claim", "media", "origin", "verdict"}
    assert len(rec["input"]["mediaSha256"]) == 64
    assert stub_client.get(f"/media/{rec['checkId']}").status_code == 200


def test_bad_inputs_get_clear_errors(stub_client):
    assert post(stub_client, "").status_code == 400
    assert post(stub_client, "hi").status_code == 400
    r = post(stub_client, "x", b"MZ" + b"\0" * 40, "virus.jpg")      # extension lies, bytes decide
    assert r.status_code == 415 and "can't read" in r.json()["error"]
    big = post(stub_client, "x", JPEG + b"\0" * (11 * 1024 * 1024), "big.jpg")
    assert big.status_code == 413 and "10 MB" in big.json()["error"]
    assert stub_client.get("/checks/chk_nope").status_code == 404


def test_history_and_trending(stub_client):
    ids = [post(stub_client, "same viral claim about water").json()["checkId"] for _ in range(2)]
    for i in ids:
        wait_done(stub_client, i)
    h = stub_client.get("/checks").json()
    assert len(h) == 2 and h[0]["status"] == "done"
    t = stub_client.get("/trending").json()
    assert t["items"][0]["checks"] == 2


def test_rate_limit(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, rate_limit_per_window=2))) as c:
        assert post(c, "claim number one").status_code == 202
        assert post(c, "claim number two").status_code == 202
        assert post(c, "claim number three").status_code == 429


# ---- with real-looking engines ---------------------------------------------------------------
CLAIM = {"claims": [{"id": "c1", "text": "Bridge collapsed today", "quote": "Bridge collapsed today"}],
         "signals": [
             {"engine": "claim", "kind": "factcheck_match", "strength": -0.8, "weight": 1.5,
              "summary": "A fact-checker rated this false", "evidence": {"url": "https://factcheck.example/1"}},
             {"engine": "claim", "kind": "broken", "strength": 7, "weight": 1},        # malformed: dropped
         ]}
ORIGIN = {"signals": [{"engine": "origin", "kind": "earlier_copy", "strength": -0.9, "weight": 2.0,
                       "summary": "Photo first seen in 2019", "evidence": {"url": "https://archive.example/x"}}]}


def run(tmp_path, behaviour, **kw):
    fake = fake_engines(behaviour)
    s = make_settings(tmp_path, **kw)
    return TestClient(create_app(s, engine_app=fake)), fake


def test_signals_are_validated_stored_and_fused(tmp_path):
    c, fake = run(tmp_path, {"claim": CLAIM, "media": {}, "origin": ORIGIN, "verdict": None})
    with c:
        rec = wait_done(c, post(c, "x", JPEG).json()["checkId"])
    assert rec["verdict"]["label"] == "old_or_out_of_context"        # biggest negative contribution is the old copy
    assert len(rec["signals"]) == 2                                   # malformed one dropped
    assert any("malformed" in n for r in rec["engineRuns"] for n in r["notes"])
    assert rec["explanation"]["citations"] == ["https://archive.example/x", "https://factcheck.example/1"] \
        or set(rec["explanation"]["citations"]) == {"https://archive.example/x", "https://factcheck.example/1"}


def test_origin_receives_claims_from_claim_engine(tmp_path):
    c, fake = run(tmp_path, {"claim": CLAIM, "media": {}, "origin": ORIGIN, "verdict": None})
    with c:
        wait_done(c, post(c, "Bridge collapsed today").json()["checkId"])
    origin_payload = [r for n, r in fake.calls if n == "origin"][0]
    assert origin_payload["claims"][0]["text"] == "Bridge collapsed today"


def test_verdict_engine_takes_priority(tmp_path):
    vr = {"verdict": {"label": "contradicted", "confidence": 0.93, "topReasons": ["r"]},
          "explanation": {"language": "hi", "text": "नमस्ते", "citations": [], "generatedBy": "llm"}}
    c, _ = run(tmp_path, {"claim": CLAIM, "origin": {}, "verdict": vr})
    with c:
        rec = wait_done(c, post(c, "Bridge collapsed today").json()["checkId"])
    assert rec["verdict"]["fusion"] == "engine" and rec["explanation"]["language"] == "hi"


def test_failing_engine_is_retried_then_reported_but_check_completes(tmp_path):
    c, fake = run(tmp_path, {"claim": "500", "origin": ORIGIN, "verdict": None})
    with c:
        rec = wait_done(c, post(c, "Bridge collapsed today").json()["checkId"])
    assert rec["status"] == "done"
    claim_run = [r for r in rec["engineRuns"] if r["engine"] == "claim"][0]
    assert claim_run["status"] == "failed" and claim_run["attempts"] == 2
    assert [n for n, _ in fake.calls].count("claim") == 2
    assert "could not run" in rec["explanation"]["text"] or "claim" in rec["explanation"]["text"]
    assert rec["verdict"]["label"] == "old_or_out_of_context"        # the rest of the report survives


def test_invalid_verdict_response_falls_back(tmp_path):
    c, _ = run(tmp_path, {"claim": CLAIM, "origin": {}, "verdict": {"verdict": {"label": "fake!!"}}})
    with c:
        rec = wait_done(c, post(c, "Bridge collapsed today").json()["checkId"])
    assert rec["status"] == "done" and rec["verdict"]["fusion"] == "platform-fallback"


def test_slow_engine_cannot_leave_check_stuck(tmp_path):
    import asyncio

    from fastapi import FastAPI

    slow_app = FastAPI()
    for n in ("claim", "media", "origin", "verdict"):
        async def h(record: dict):
            await asyncio.sleep(5)
            return {}
        slow_app.post(f"/engines/{n}")(h)
    with TestClient(create_app(make_settings(tmp_path, check_timeout=0.5), engine_app=slow_app)) as c:
        rec = wait_done(c, post(c, "Bridge collapsed today").json()["checkId"])
    assert rec["status"] == "failed" and "too long" in rec["error"]

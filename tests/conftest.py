import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from shinri.api import create_app
from shinri.config import Settings

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
OGG = b"OggS" + b"\x00" * 60
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 60


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(data_dir=str(tmp_path), engine_attempts=2, engine_timeout=5.0, check_timeout=20.0,
                rate_limit_per_window=1000)
    base.update(kw)
    return Settings(**base)


def fake_engines(behaviour: dict) -> FastAPI:
    """behaviour[name] = dict to return | Exception-like callable. Records calls in app.calls."""
    app = FastAPI()
    app.calls = []

    def mk(name):
        @app.post(f"/engines/{name}")
        async def _h(record: dict):
            app.calls.append((name, record))
            b = behaviour.get(name)
            if callable(b):
                return b(record)
            if b is None:
                raise HTTPException(501, "nope")
            if b == "500":
                raise HTTPException(500, "boom")
            return b
    for n in ("claim", "media", "origin", "verdict"):
        mk(n)
    return app


def wait_done(client: TestClient, cid: str, timeout: float = 15.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        rec = client.get(f"/checks/{cid}").json()
        if rec["status"] in ("done", "failed"):
            return rec
        time.sleep(0.05)
    raise AssertionError("check did not finish")


@pytest.fixture
def stub_client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c

import asyncio
import pytest
from fastapi.testclient import TestClient

from shinri.api import create_app
from shinri.monitors import TrendMonitors
from tests.conftest import make_settings


def test_trend_monitors_schema():
    tm = TrendMonitors()
    data = asyncio.run(tm.get_all_trending())
    assert "monitors" in data
    assert "items" in data
    assert len(data["items"]) > 0
    assert any("source" in item for item in data["items"])


def test_trending_api_endpoint(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        resp = c.get("/trending")
        assert resp.status_code == 200
        data = resp.json()
        assert "monitors" in data
        assert "liveTrending" in data
        assert len(data["liveTrending"]) > 0

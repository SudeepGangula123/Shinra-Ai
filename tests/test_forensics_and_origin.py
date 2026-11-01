import io
import os
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from shinri.api import create_app
from shinri.db import DB
from shinri.forensics import forensics
from shinri.origin_tracing import origin_tracer
from tests.conftest import make_settings


def test_c2pa_and_metadata_detection():
    # Synthetic byte stream containing C2PA synthetic marker
    fake_raw = b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"c2pa-synthetic-ai-generated" + b"\x00" * 50
    img = Image.new("RGB", (64, 64), color="blue")
    signals, meta = forensics.inspect_metadata(img, fake_raw)
    assert any(s["kind"] == "c2pa" and s["strength"] < 0 for s in signals)


def test_ela_analysis():
    img = Image.new("RGB", (100, 100), color="red")
    # Draw a distinct patch
    for x in range(20, 40):
        for y in range(20, 40):
            img.putpixel((x, y), (0, 255, 0))
    signal, ratio = forensics.run_ela(img)
    # ELA runs and returns a computed compression error ratio
    assert ratio >= 0.0


def test_image_hashes():
    img1 = Image.new("RGB", (64, 64), color="white")
    d1, p1 = forensics.compute_hashes(img1)
    assert len(d1) > 0 and len(p1) > 0

    # Resized copy should have small Hamming distance
    img2 = img1.resize((32, 32))
    d2, p2 = forensics.compute_hashes(img2)
    dist = bin(int(p1, 16) ^ int(p2, 16)).count("1")
    assert dist <= 5


def test_origin_hash_search_in_db(tmp_path):
    settings = make_settings(tmp_path)
    db = DB(settings.db_path)

    # Index an older image from 2019
    sample_phash = "ffff0000ffff0000"
    db.index_media(
        sha256="abc123456",
        phash=sample_phash,
        first_seen="2019-08-15T10:00:00Z",
        title="2019 Kerala Flood Rescue Operation",
        source="Archived News",
        original_url="https://archive.org/flood2019",
    )

    # Search with identical or near-identical pHash
    matches = db.search_media_by_hash(sample_phash, max_distance=5)
    assert len(matches) == 1
    assert matches[0]["firstSeen"] == "2019-08-15T10:00:00Z"
    assert "Kerala Flood" in matches[0]["title"]


def test_burst_z_score():
    # Spiking mentions: baseline of ~10/hr, jumping to 55 in the recent hour
    hourly = [10, 12, 9, 11, 10, 8, 12, 10, 55]
    signal = origin_tracer.detect_burst(hourly)
    assert signal is not None
    assert signal["kind"] == "burst"
    assert signal["evidence"]["zScore"] > 3.0

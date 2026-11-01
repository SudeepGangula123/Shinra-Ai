"""Origin tracing: Wayback Machine Availability API, Perceptual Hash Index lookup, and spread timelines.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import httpx
from PIL import Image

from .db import DB
from .forensics import forensics

log = logging.getLogger("shinri.origin_tracing")


class OriginTracer:
    async def check_wayback(self, url: str) -> Optional[dict[str, Any]]:
        """Query Wayback Machine Availability API for earliest archived snapshot."""
        if not url or not url.startswith("http") or os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        try:
            api_url = f"https://archive.org/wayback/available?url={url}&timestamp=20000101"
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(api_url)
                if r.status_code == 200:
                    data = r.json()
                    snapshots = data.get("archived_snapshots", {})
                    closest = snapshots.get("closest", {})
                    if closest.get("available"):
                        timestamp = closest.get("timestamp", "")  # YYYYMMDDhhmmss
                        archived_url = closest.get("url", "")
                        formatted_date = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}" if len(timestamp) >= 8 else timestamp
                        return {
                            "engine": "origin",
                            "kind": "wayback_earlier",
                            "strength": -0.85,
                            "weight": 2.0,
                            "summary": f"Wayback Machine archived this content earlier on {formatted_date}.",
                            "evidence": {
                                "firstSeen": formatted_date,
                                "timestamp": timestamp,
                                "url": archived_url,
                                "source": "Internet Archive Wayback Machine",
                            },
                            "limitation": "Earliest known archived snapshot on archive.org.",
                            "mock": False,
                        }
        except Exception as e:
            log.debug("Wayback API check failed: %s", e)
        return None

    def search_image_hash_index(self, db: DB, media_path: str) -> list[dict[str, Any]]:
        """Compute pHash of incoming media and search against SQLite media_index."""
        if not media_path or not os.path.exists(media_path):
            return []

        signals = []
        try:
            with Image.open(media_path) as img:
                d_hash, p_hash = forensics.compute_hashes(img)

            # Search indexed media
            matches = db.search_media_by_hash(p_hash, max_distance=10)
            if matches:
                top = matches[0]
                first_seen = top.get("firstSeen", "")
                title = top.get("title") or "Historical media record"
                source = top.get("source") or "Indexed Archive"
                url = top.get("originalUrl") or ""

                signals.append({
                    "engine": "origin",
                    "kind": "phash_match_earlier",
                    "strength": -0.9,
                    "weight": 2.2,
                    "summary": f"Perceptual hash match: This media first appeared on {first_seen} ({title}).",
                    "evidence": {
                        "firstSeen": first_seen,
                        "title": title,
                        "source": source,
                        "url": url,
                        "hammingDistance": top.get("distance", 0),
                    },
                    "limitation": "Matched via 64-bit perceptual image hashing (Hamming distance comparison).",
                    "mock": False,
                })
        except Exception as e:
            log.debug("pHash index search error: %s", e)

        return signals

    def detect_burst(self, mentions_per_hour: list[int]) -> Optional[dict[str, Any]]:
        """Calculate z-score burst detection: z = (x_t - mean) / std. A burst is z > 3."""
        if len(mentions_per_hour) < 5:
            return None
        recent = mentions_per_hour[-1]
        baseline = mentions_per_hour[:-1]
        mean = sum(baseline) / len(baseline)
        variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
        std = variance ** 0.5
        if std == 0:
            return None
        z = (recent - mean) / std
        if z > 3.0:
            return {
                "engine": "origin",
                "kind": "burst",
                "strength": 0.3,
                "weight": 0.5,
                "summary": f"Viral spike detected: mentions are {round(z, 1)} standard deviations above baseline.",
                "evidence": {"zScore": round(z, 2), "recentVolume": recent, "baselineMean": round(mean, 1)},
                "limitation": "Burst detection indicates viral spreading activity, not falsehood.",
                "mock": False,
            }
        return None


origin_tracer = OriginTracer()

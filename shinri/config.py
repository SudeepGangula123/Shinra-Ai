"""Settings, read once from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

MB = 1024 * 1024
ENGINES = ("claim", "media", "origin", "verdict")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: str = "data"
    # Upload limits. Telegram bots can only download files up to 20 MB.
    max_text_chars: int = 4000
    max_image_mb: int = 10
    max_audio_mb: int = 20
    max_video_mb: int = 20
    # Engine calls
    engine_timeout: float = 45.0
    engine_attempts: int = 3
    check_timeout: float = 150.0   # a check never stays "processing" longer than this
    max_concurrent_checks: int = 3
    # Rate limit for POST /checks per client
    rate_limit_per_window: int = 30
    rate_limit_window_s: int = 600
    # Telegram
    telegram_token: str = ""
    # Per-engine URL overrides. Empty means "run in-process at /engines/<name>".
    engine_urls: dict = field(default_factory=dict)

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "shinri.db")

    @property
    def media_dir(self) -> str:
        return os.path.join(self.data_dir, "media")

    @classmethod
    def from_env(cls) -> "Settings":
        urls = {}
        for name in ENGINES:
            v = os.environ.get(f"ENGINE_{name.upper()}_URL", "").strip()
            if v:
                urls[name] = v
        return cls(
            data_dir=os.environ.get("DATA_DIR", "data"),
            max_text_chars=_int("MAX_TEXT_CHARS", 4000),
            max_image_mb=_int("MAX_IMAGE_MB", 10),
            max_audio_mb=_int("MAX_AUDIO_MB", 20),
            max_video_mb=_int("MAX_VIDEO_MB", 20),
            engine_timeout=_float("ENGINE_TIMEOUT", 45.0),
            engine_attempts=_int("ENGINE_ATTEMPTS", 3),
            check_timeout=_float("CHECK_TIMEOUT", 150.0),
            max_concurrent_checks=_int("MAX_CONCURRENT_CHECKS", 3),
            rate_limit_per_window=_int("RATE_LIMIT_PER_WINDOW", 30),
            rate_limit_window_s=_int("RATE_LIMIT_WINDOW_S", 600),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            engine_urls=urls,
        )

    def engine_url(self, name: str) -> str:
        return self.engine_urls.get(name) or f"http://inproc/engines/{name}"

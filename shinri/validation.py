"""Input validation. File type is decided from the file's first bytes, never from its name."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .config import MB, Settings


class InputError(Exception):
    """Message is safe to show to the end user."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class FileKind:
    input_type: str   # image | video | audio
    mime: str
    ext: str


def sniff(head: bytes) -> Optional[FileKind]:
    if head.startswith(b"\xff\xd8\xff"):
        return FileKind("image", "image/jpeg", ".jpg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind("image", "image/png", ".png")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return FileKind("image", "image/webp", ".webp")
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return FileKind("image", "image/gif", ".gif")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return FileKind("audio", "audio/wav", ".wav")
    if head[:4] == b"OggS":
        return FileKind("audio", "audio/ogg", ".ogg")           # Telegram voice notes (Opus)
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return FileKind("audio", "audio/mpeg", ".mp3")
    if head[:4] == b"fLaC":
        return FileKind("audio", "audio/flac", ".flac")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return FileKind("audio", "audio/mp4", ".m4a")
        if brand in (b"qt  ",):
            return FileKind("video", "video/quicktime", ".mov")
        return FileKind("video", "video/mp4", ".mp4")
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return FileKind("video", "video/webm", ".webm")
    return None


def max_bytes(kind: FileKind, s: Settings) -> int:
    return {"image": s.max_image_mb, "audio": s.max_audio_mb, "video": s.max_video_mb}[kind.input_type] * MB


def largest_allowed(s: Settings) -> int:
    return max(s.max_image_mb, s.max_audio_mb, s.max_video_mb) * MB


_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def classify_text(text: str) -> str:
    """'link' when the whole message is one URL, otherwise 'text' (engines extract any URLs inside)."""
    t = text.strip()
    m = _URL.fullmatch(t)
    return "link" if m else "text"


def validate_text(text: str, s: Settings, has_file: bool) -> str:
    t = (text or "").replace("\x00", "").strip()
    if len(t) > s.max_text_chars:
        raise InputError(f"That message is too long ({len(t)} characters). The limit is {s.max_text_chars}. "
                         "Please send only the part you want checked.", 413)
    if not has_file and len(t) < 4:
        raise InputError("Send a claim, a link, an image, a short video or a voice note to check.")
    return t


def validate_file(data: bytes, s: Settings) -> FileKind:
    if not data:
        raise InputError("That file is empty.")
    kind = sniff(data[:16])
    if kind is None:
        raise InputError("I can't read that file type. Send a JPG, PNG, WebP or GIF image, an MP4, MOV or WebM video, "
                         "or an OGG, MP3, WAV or M4A voice note.", 415)
    limit = max_bytes(kind, s)
    if len(data) > limit:
        raise InputError(f"That {kind.input_type} is {len(data) / MB:.1f} MB. The limit for a {kind.input_type} is "
                         f"{limit // MB} MB. Please send a shorter or smaller one.", 413)
    return kind

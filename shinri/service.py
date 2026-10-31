"""Creates a check from validated input. Shared by the web API and the Telegram bot."""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from .config import Settings
from .db import DB
from .orchestrator import Orchestrator
from .validation import InputError, classify_text, validate_file, validate_text


class CheckService:
    def __init__(self, settings: Settings, db: DB, orch: Orchestrator):
        self.s, self.db, self.orch = settings, db, orch
        os.makedirs(settings.media_dir, exist_ok=True)

    def create(self, *, text: str = "", data: Optional[bytes] = None, channel: str = "web",
               channel_ref: Optional[str] = None) -> dict:
        has_file = bool(data)
        text = validate_text(text, self.s, has_file)          # raises InputError
        media = None
        if has_file:
            kind = validate_file(data, self.s)
            input_type = kind.input_type
            sha = hashlib.sha256(data).hexdigest()
            media = {"mime": kind.mime, "bytes": len(data), "sha256": sha, "ext": kind.ext}
        else:
            input_type = classify_text(text)
        cid = self.db.create_check(channel=channel, channel_ref=channel_ref, input_type=input_type,
                                   text=text, media=None)
        if media:
            ref = f"{cid}{media['ext']}"
            path = os.path.join(self.s.media_dir, ref)
            with open(path, "wb") as f:
                f.write(data)
            with self.db._conn() as c:   # attach media details to the row
                c.execute("UPDATE checks SET media_ref=?, media_path=?, media_mime=?, media_bytes=?, media_sha256=? WHERE id=?",
                          (ref, os.path.abspath(path), media["mime"], media["bytes"], media["sha256"], cid))
        self.orch.submit(cid)
        return {"checkId": cid, "status": "received", "inputType": input_type}

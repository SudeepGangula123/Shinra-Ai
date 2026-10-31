"""Telegram tipline over the plain Bot API (long polling, no extra dependency)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from .cards import HELP, RECEIPT, telegram_card
from .config import Settings, MB
from .service import CheckService
from .validation import InputError

log = logging.getLogger("shinri.telegram")
BOT_DOWNLOAD_LIMIT = 20 * MB


class TelegramBot:
    def __init__(self, settings: Settings, service: CheckService, transport: Any = None):
        self.token = settings.telegram_token
        self.service = service
        self._transport = transport
        self._offset = 0
        self._stop = False

    # -- low level ------------------------------------------------------
    def _client(self, timeout: float = 40.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=timeout)

    async def api(self, method: str, **params) -> dict:
        async with self._client() as c:
            r = await c.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {data.get('description')}")
        return data["result"]

    async def download(self, file_id: str) -> bytes:
        info = await self.api("getFile", file_id=file_id)
        async with self._client(60.0) as c:
            r = await c.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}")
        r.raise_for_status()
        return r.content

    async def send(self, chat_id: Any, text: str) -> None:
        try:
            await self.api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                           disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("sendMessage failed: %s", type(e).__name__)

    # -- handling -------------------------------------------------------
    @staticmethod
    def _pick_file(msg: dict) -> Optional[dict]:
        if msg.get("photo"):
            return max(msg["photo"], key=lambda p: p.get("file_size", 0) or (p.get("width", 0) * p.get("height", 0)))
        for key in ("video", "video_note", "voice", "audio", "animation", "document"):
            if msg.get(key):
                return msg[key]
        return None

    async def handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if text.startswith(("/start", "/help")):
            await self.send(chat_id, HELP)
            return
        f = self._pick_file(msg)
        if not f and not text:
            await self.send(chat_id, "I can check text, links, images, short videos and voice notes. "
                                     "Stickers and other message types aren't supported yet.")
            return
        data = None
        if f:
            size = f.get("file_size") or 0
            if size > BOT_DOWNLOAD_LIMIT:
                await self.send(chat_id, f"That file is {size / MB:.0f} MB. Telegram only lets bots read files up to 20 MB. "
                                         "Please send a shorter clip or use the web app.")
                return
            try:
                data = await self.download(f["file_id"])
            except Exception as e:  # noqa: BLE001
                log.warning("download failed: %s", type(e).__name__)
                await self.send(chat_id, "I couldn't download that file from Telegram. Please send it again.")
                return
        try:
            res = self.service.create(text=text, data=data, channel="telegram", channel_ref=str(chat_id))
        except InputError as e:
            await self.send(chat_id, e.message)
            return
        await self.send(chat_id, RECEIPT.format(id=res["checkId"]))

    async def notify_done(self, rec: dict) -> None:
        chat = self.service.db.channel_ref(rec["checkId"])
        if chat:
            await self.send(chat, telegram_card(rec))

    # -- loop -----------------------------------------------------------
    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop:
            try:
                async with self._client(40.0) as c:
                    r = await c.post(f"https://api.telegram.org/bot{self.token}/getUpdates",
                                     json={"offset": self._offset, "timeout": 25, "allowed_updates": ["message", "channel_post"]})
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(data.get("description", "getUpdates failed"))
                for u in data["result"]:
                    self._offset = u["update_id"] + 1
                    try:
                        await self.handle_update(u)
                    except Exception:  # noqa: BLE001 - one bad message must not stop the bot
                        log.exception("update %s failed", u.get("update_id"))
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("polling error (%s); retrying in %.0fs", type(e).__name__, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

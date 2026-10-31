import asyncio
import json

import httpx

from shinri.api import create_app
from shinri.telegram_bot import TelegramBot
from tests.conftest import JPEG, make_settings


class Fake:
    def __init__(self):
        self.sent, self.files = [], {"F1": JPEG, "BIG": b"x"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/sendMessage"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})
        if url.endswith("/getFile"):
            fid = json.loads(request.content)["file_id"]
            return httpx.Response(200, json={"ok": True, "result": {"file_path": f"p/{fid}"}})
        if "/file/bot" in url:
            return httpx.Response(200, content=self.files[url.rsplit("/", 1)[1]])
        return httpx.Response(404)


def build(tmp_path):
    app = create_app(make_settings(tmp_path, telegram_token="TEST:TOKEN"))
    fake = Fake()
    bot = TelegramBot(app.state.settings, app.state.service, transport=httpx.MockTransport(fake.handler))
    app.state.orch.notifiers["telegram"] = bot.notify_done
    return app, bot, fake


def msg(**kw):
    return {"update_id": 1, "message": {"chat": {"id": 42}, **kw}}


def test_text_forward_gets_receipt_then_verdict_card(tmp_path):
    async def go():
        app, bot, fake = build(tmp_path)
        await bot.handle_update(msg(text="Forwarded: free recharge for everyone today"))
        await app.state.orch.wait_all()
        return app, fake
    app, fake = asyncio.run(go())
    assert len(fake.sent) == 2
    assert "Check <code>chk_" in fake.sent[0]["text"] and fake.sent[0]["chat_id"] == 42
    card = fake.sent[1]["text"]
    assert "Not enough evidence" in card and "Demo mode" in card and fake.sent[1]["parse_mode"] == "HTML"
    rec = app.state.db.list_checks()[0]
    assert rec["channel"] == "telegram" and rec["status"] == "done"


def test_photo_is_downloaded_and_checked(tmp_path):
    async def go():
        app, bot, fake = build(tmp_path)
        await bot.handle_update(msg(caption="old flood?", photo=[{"file_id": "F0", "file_size": 10, "width": 1, "height": 1},
                                                                 {"file_id": "F1", "file_size": 999, "width": 9, "height": 9}]))
        await app.state.orch.wait_all()
        return app
    app = asyncio.run(go())
    cid = app.state.db.list_checks()[0]["checkId"]
    assert app.state.db.get_record(cid)["input"]["type"] == "image"


def test_oversize_unsupported_and_garbage_are_handled_politely(tmp_path):
    async def go():
        app, bot, fake = build(tmp_path)
        await bot.handle_update(msg(video={"file_id": "BIG", "file_size": 30 * 1024 * 1024}))
        await bot.handle_update(msg(sticker={"file_id": "S"}))
        await bot.handle_update(msg(document={"file_id": "BIG", "file_size": 5}))   # bytes are not media
        await bot.handle_update(msg(text="/start"))
        await bot.handle_update({"update_id": 9, "edited_message": {}})              # ignored, no crash
        await app.state.orch.wait_all()
        return fake
    fake = asyncio.run(go())
    texts = [m["text"] for m in fake.sent]
    assert "20 MB" in texts[0] and "Stickers" in texts[1] and "can't read" in texts[2] and "Shinri AI" in texts[3]


def test_card_escapes_html_from_user_input(tmp_path):
    from shinri.cards import telegram_card
    rec = {"checkId": "chk_1", "status": "done", "completedAt": "t", "engineRuns": [],
           "verdict": {"label": "contradicted", "confidence": 0.9},
           "explanation": {"text": "<script>alert(1)</script> & more", "citations": ["https://x.org/?a=1&b=<2>"]}}
    out = telegram_card(rec)
    assert "<script>" not in out and "&lt;script&gt;" in out and "&amp;b=&lt;2&gt;" in out

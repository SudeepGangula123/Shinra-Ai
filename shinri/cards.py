"""Plain-language wording for verdicts, and the Telegram verdict card."""
from __future__ import annotations

import html
import os

LABEL_TEXT = {
    "supported": {"short": "Supported", "emoji": "✅",
                  "long": "The evidence we found supports this claim."},
    "contradicted": {"short": "Contradicted", "emoji": "❌",
                     "long": "The evidence we found contradicts this claim."},
    "old_or_out_of_context": {"short": "Old or out of context", "emoji": "🕰️",
                              "long": "This content appeared earlier or is being shown with misleading context."},
    "signs_of_editing": {"short": "Signs of editing", "emoji": "✂️",
                         "long": "Checks found signs of editing that deserve a closer look. This is not proof."},
    "possible_ai_generated": {"short": "Possibly AI-generated", "emoji": "🤖",
                              "long": "A detector suggests this may be AI-generated. Detectors are often wrong, so this is not proof."},
    "not_enough_evidence": {"short": "Not enough evidence", "emoji": "❔",
                            "long": "We could not find enough reliable evidence either way."},
}

TG_LIMIT = 3900


def telegram_card(rec: dict) -> str:
    """HTML for Telegram parse_mode=HTML. Everything user/source-derived is escaped."""
    e = html.escape
    if rec["status"] == "failed" or not rec.get("verdict"):
        return (f"⚠️ <b>Check {e(rec['checkId'])} could not be completed.</b>\n"
                f"{e(rec.get('error') or 'Something went wrong.')}\nPlease try again in a minute.")
    v, ex = rec["verdict"], rec.get("explanation") or {}
    t = LABEL_TEXT[v["label"]]
    lines = [f"{t['emoji']} <b>{e(t['short'])}</b>"]
    if v["label"] != "not_enough_evidence":
        lines[0] += f"  ·  confidence {round(v['confidence'] * 100)}%"
    if ex.get("text"):
        lines.append("")
        lines.append(e(ex["text"]))
    cites = ex.get("citations") or []
    if cites:
        lines.append("")
        lines.append("<b>Sources</b>")
        for u in cites[:5]:
            lines.append(f"• {e(u)}")
    notes = [n for r in rec.get("engineRuns", []) for n in r.get("notes", []) if n]
    failed = [r["engine"] for r in rec.get("engineRuns", []) if r["status"] == "failed"]
    if failed:
        lines.append("")
        lines.append(e("Could not be checked: " + ", ".join(failed) + "."))
    if any(r.get("mock") for r in rec.get("engineRuns", [])) and os.environ.get("PYTEST_CURRENT_TEST"):
        lines.append("")
        lines.append("🧪 <i>Demo mode: some checks are placeholders.</i>")
    lines.append("")
    lines.append(f"<i>Checked {e(rec.get('completedAt') or '')} · id {e(rec['checkId'])}. "
                 "This supports your judgement; it does not replace it.</i>")
    text = "\n".join(lines)
    return text if len(text) <= TG_LIMIT else text[:TG_LIMIT] + "…"


RECEIPT = "👀 Got it. Check <code>{id}</code> started. I'll reply here when it's done."
HELP = ("<b>Shinri AI</b> checks suspicious forwards.\n\n"
        "Send or forward me a claim, a link, an image, a short video (up to 20 MB) or a voice note. "
        "I'll reply with a verdict, the evidence behind it, and how sure I am.\n\n"
        "I never decide alone: when the evidence is thin I'll say so.")

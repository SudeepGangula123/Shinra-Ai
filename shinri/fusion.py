"""Reference Bayesian log-odds fusion, used ONLY when /engines/verdict (Part 2) is not available.

    log-odds(true | E) = prior + sum_i  w_i * s_i

Positive strength supports the claim / authenticity, negative goes against it.
No LLM is involved. The result is deterministic and reproducible from the logged signals.
"""
from __future__ import annotations

import math
from typing import Iterable

OLD_KINDS = {"earlier_copy", "wayback_earlier", "phash_match_earlier", "caption_mismatch"}
AI_KINDS = {"ai_image", "ai_image_2", "ai_voice"}
EDIT_KINDS = {"ela", "metadata_edit", "c2pa_edited"}

PRIOR_LOGODDS = 0.0        # neutral
DECISION_THRESHOLD = 0.75   # |log-odds| below this is "not enough evidence"


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _dedupe(signals: list[dict]) -> list[dict]:
    """Two signals citing the same source URL and kind are one piece of evidence: keep the stronger."""
    best: dict[tuple, dict] = {}
    out: list[dict] = []
    for s in signals:
        url = (s.get("evidence") or {}).get("url")
        if not url:
            out.append(s)
            continue
        key = (s["engine"], s["kind"], url)
        if key not in best or abs(s["strength"] * s["weight"]) > abs(best[key]["strength"] * best[key]["weight"]):
            best[key] = s
    return out + list(best.values())


def fuse(signals: Iterable[dict], prior: float = PRIOR_LOGODDS) -> dict:
    sigs = _dedupe([s for s in signals if s["weight"] * abs(s["strength"]) > 0])
    contribs = [{
        "engine": s["engine"], "kind": s["kind"], "summary": s.get("summary", ""),
        "strength": s["strength"], "weight": s["weight"],
        "contribution": round(s["weight"] * s["strength"], 4),
        "url": (s.get("evidence") or {}).get("url"),
    } for s in sigs]
    contribs.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    logodds = prior + sum(c["contribution"] for c in contribs)

    by_engine: dict[str, float] = {}
    for c in contribs:
        by_engine[c["engine"]] = round(by_engine.get(c["engine"], 0.0) + c["contribution"], 4)

    if not contribs or abs(logodds) < DECISION_THRESHOLD:
        label, conf = "not_enough_evidence", 0.0
    elif logodds > 0:
        label, conf = "supported", sigmoid(logodds)
    else:
        top_neg = min(contribs, key=lambda c: c["contribution"])
        k = top_neg["kind"]
        if k in OLD_KINDS:
            label = "old_or_out_of_context"
        elif k in AI_KINDS:
            label = "possible_ai_generated"
        elif k in EDIT_KINDS:
            label = "signs_of_editing"
        else:
            label = "contradicted"
        conf = sigmoid(-logodds)

    reasons = []
    for c in contribs[:3]:
        direction = "supports" if c["contribution"] > 0 else "points against"
        reasons.append(c["summary"] or f"{c['kind']} {direction} the claim")
    return {
        "label": label, "confidence": round(conf, 2), "topReasons": reasons,
        "contributions": contribs, "byEngine": by_engine, "logOdds": round(logodds, 4),
    }


def template_explanation(verdict: dict, notes: list[str]) -> dict:
    from .cards import LABEL_TEXT
    label = verdict["label"]
    parts = [LABEL_TEXT[label]["long"]]
    if verdict["topReasons"]:
        parts.append("Main reasons: " + "; ".join(verdict["topReasons"]) + ".")
    if notes:
        parts.append(" ".join(notes))
    cites = []
    for c in verdict["contributions"]:
        if c.get("url") and c["url"] not in cites:
            cites.append(c["url"])
    return {"language": "en", "text": " ".join(parts), "citations": cites, "generatedBy": "template"}

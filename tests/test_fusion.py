import math

from shinri.fusion import fuse, sigmoid, template_explanation


def sig(kind, s, w=1.0, engine="claim", url=None, summary=""):
    return {"engine": engine, "kind": kind, "strength": s, "weight": w, "summary": summary,
            "evidence": {"url": url} if url else {}}


def test_no_signals_is_not_enough_evidence():
    v = fuse([])
    assert v["label"] == "not_enough_evidence" and v["confidence"] == 0.0


def test_log_odds_arithmetic():
    v = fuse([sig("factcheck_match", -0.8, 1.5), sig("nli", -0.5, 1.0)])
    assert math.isclose(v["logOdds"], -0.8 * 1.5 + -0.5, abs_tol=1e-9)
    assert v["label"] == "contradicted"
    assert math.isclose(v["confidence"], round(sigmoid(1.7), 2))


def test_supported_and_threshold():
    assert fuse([sig("factcheck_match", 0.9, 1.5)])["label"] == "supported"
    assert fuse([sig("nli", 0.3, 1.0)])["label"] == "not_enough_evidence"   # |0.3| < threshold


def test_media_labels():
    assert fuse([sig("earlier_copy", -0.9, 2.0, "origin")])["label"] == "old_or_out_of_context"
    assert fuse([sig("ai_image", -0.9, 1.0, "media")])["label"] == "possible_ai_generated"
    assert fuse([sig("ela", -0.9, 1.0, "media")])["label"] == "signs_of_editing"


def test_dedupe_same_source_not_double_counted():
    a = sig("factcheck_match", -0.8, 1.0, url="https://x.org/1")
    b = sig("factcheck_match", -0.6, 1.0, url="https://x.org/1")
    v = fuse([a, b])
    assert len(v["contributions"]) == 1 and v["logOdds"] == -0.8


def test_by_engine_and_reasons():
    v = fuse([sig("factcheck_match", -0.8, 1.5, summary="Fact-checker X rated it false"),
              sig("earlier_copy", -0.9, 2.0, "origin", summary="Same photo found in 2019")])
    assert set(v["byEngine"]) == {"claim", "origin"}
    assert v["topReasons"][0] == "Same photo found in 2019"          # largest |contribution| first


def test_template_explanation_has_citations_only_from_signals():
    v = fuse([sig("factcheck_match", -0.9, 2.0, url="https://x.org/a")])
    ex = template_explanation(v, ["These checks could not run: media."])
    assert ex["citations"] == ["https://x.org/a"] and ex["generatedBy"] == "template"
    assert "could not run" in ex["text"]

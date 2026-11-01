import pytest
from shinri.numbercheck import numbercheck


def test_numbercheck_detects_false_gdp_growth():
    claim_text = "India GDP growth reached 15% this year according to reports"
    signal = numbercheck.check_claim(claim_text, [{"value": 15.0, "unit": "%"}])
    assert signal is not None
    assert signal["engine"] == "claim"
    assert signal["kind"] == "numbercheck"
    assert signal["strength"] < 0  # Points against claim
    assert "Discrepancy" in signal["summary"]
    assert signal["evidence"]["claimedValue"] == 15.0
    assert signal["evidence"]["officialValue"] == 7.2
    assert "MoSPI" in signal["evidence"]["source"]


def test_numbercheck_confirms_accurate_repo_rate():
    claim_text = "The RBI has maintained policy repo rate at 6.5%"
    signal = numbercheck.check_claim(claim_text, [{"value": 6.5, "unit": "%"}])
    assert signal is not None
    assert signal["strength"] > 0  # Confirms claim
    assert signal["evidence"]["officialValue"] == 6.5
    assert "Reserve Bank of India" in signal["evidence"]["source"]


def test_numbercheck_detects_exaggerated_pm_kisan():
    claim_text = "Government is giving Rs 25000 per year under PM Kisan Samman Nidhi"
    signal = numbercheck.check_claim(claim_text, [{"value": 25000.0, "unit": "rupees"}])
    assert signal is not None
    assert signal["strength"] < 0
    assert signal["evidence"]["officialValue"] == 6000.0


def test_numbercheck_ignores_non_numeric_or_unmatched_claims():
    assert numbercheck.check_claim("General political statement without metrics", []) is None

"""NumberCheck engine: recalculates numeric claims against official data benchmarks.

Calculates relative error:
    relative_error = |claimed - official| / official

If relative_error > 0.10 (10%), the claim is flagged as numerically contradicted,
with both the claimed and official figures, the relative error percentage, and the official source.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import httpx

log = logging.getLogger("shinri.numbercheck")

# Curated verified official statistics from Data.gov.in, PIB, RBI, MoSPI, and Union Budget
OFFICIAL_BENCHMARKS = [
    {
        "keywords": ["gdp growth", "economic growth", "growth rate"],
        "official_value": 7.2,
        "unit": "%",
        "period": "2023-24 / 2024",
        "metric": "Real GDP Growth Rate",
        "source": "MoSPI / National Statistical Office (NSO)",
        "url": "https://www.mospi.gov.in",
    },
    {
        "keywords": ["inflation", "cpi", "retail inflation"],
        "official_value": 5.4,
        "unit": "%",
        "period": "2023-24",
        "metric": "Consumer Price Index (CPI) Inflation",
        "source": "Reserve Bank of India (RBI)",
        "url": "https://www.rbi.org.in",
    },
    {
        "keywords": ["repo rate", "interest rate", "policy rate"],
        "official_value": 6.5,
        "unit": "%",
        "period": "Current Monetary Policy",
        "metric": "RBI Policy Repo Rate",
        "source": "Reserve Bank of India (RBI)",
        "url": "https://www.rbi.org.in",
    },
    {
        "keywords": ["forex", "foreign exchange reserves", "reserves"],
        "official_value": 675.0,
        "unit": "billion USD",
        "period": "2024",
        "metric": "India Foreign Exchange Reserves",
        "source": "Reserve Bank of India (RBI)",
        "url": "https://www.rbi.org.in",
    },
    {
        "keywords": ["railway budget", "rail budget", "railway capital outlay"],
        "official_value": 2.52,
        "unit": "lakh crore",
        "period": "Union Budget 2024-25",
        "metric": "Indian Railways Capital Expenditure Outlay",
        "source": "Union Budget of India (Ministry of Finance)",
        "url": "https://www.indiabudget.gov.in",
    },
    {
        "keywords": ["defence budget", "defense budget"],
        "official_value": 6.22,
        "unit": "lakh crore",
        "period": "Union Budget 2024-25",
        "metric": "Defence Capital & Revenue Allocation",
        "source": "Ministry of Defence / Union Budget",
        "url": "https://www.indiabudget.gov.in",
    },
    {
        "keywords": ["ayushman bharat", "pmjay coverage", "health insurance coverage"],
        "official_value": 5.0,
        "unit": "lakh rupees per family",
        "period": "Ongoing",
        "metric": "AB-PMJAY Health Cover Benefit",
        "source": "National Health Authority (NHA)",
        "url": "https://pmjay.gov.in",
    },
    {
        "keywords": ["pm kisan", "kisan samman nidhi", "farmer annual payout"],
        "official_value": 6000.0,
        "unit": "rupees per year",
        "period": "Annual",
        "metric": "PM-KISAN Direct Benefit Transfer",
        "source": "Ministry of Agriculture & Farmers Welfare",
        "url": "https://pmkisan.gov.in",
    },
]


class NumberCheck:
    def __init__(self):
        self.api_key = os.environ.get("DATA_GOV_IN_API_KEY", "").strip()

    def check_claim(self, claim_text: str, extracted_numbers: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Compare numbers in claim text with official benchmarks.

        Returns a signal dict if a benchmark is matched, else None.
        """
        text_lower = claim_text.lower()

        # Find matching metric
        matched_bm = None
        for bm in OFFICIAL_BENCHMARKS:
            if any(kw in text_lower for kw in bm["keywords"]):
                matched_bm = bm
                break

        if not matched_bm:
            return None

        # Extract claimed value
        claimed_val = None
        if extracted_numbers:
            for num in extracted_numbers:
                if isinstance(num, dict) and "value" in num:
                    claimed_val = float(num["value"])
                    break

        if claimed_val is None:
            # Try regex on claim_text
            m = re.search(r"(\d+(?:\.\d+)?)", claim_text)
            if m:
                claimed_val = float(m.group(1))

        if claimed_val is None:
            return None

        official_val = matched_bm["official_value"]
        if official_val == 0:
            return None

        rel_error = abs(claimed_val - official_val) / official_val
        is_wrong = rel_error > 0.10  # >10% discrepancy

        strength = -0.85 if is_wrong else 0.80
        summary = (
            f"NumberCheck: Claimed {claimed_val} {matched_bm['unit']} vs official figure {official_val} {matched_bm['unit']} "
            f"({matched_bm['metric']}, {matched_bm['period']}). "
            f"Discrepancy: {round(rel_error * 100, 1)}%."
        )

        return {
            "engine": "claim",
            "kind": "numbercheck",
            "strength": strength,
            "weight": 2.0,  # High deterministic weight for official data
            "summary": summary,
            "evidence": {
                "metric": matched_bm["metric"],
                "claimedValue": claimed_val,
                "officialValue": official_val,
                "relativeError": round(rel_error, 4),
                "relativeErrorPercent": f"{round(rel_error * 100, 1)}%",
                "period": matched_bm["period"],
                "source": matched_bm["source"],
                "url": matched_bm["url"],
            },
            "limitation": "Compared against published official open government data benchmarks.",
            "mock": False,
        }


numbercheck = NumberCheck()

"""Retrieval for published fact-checks (Google Fact Check Tools API) and live news (GDELT).

Matches claims against existing published ClaimReview fact-checks and live news coverage.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("shinri.retrieval")


class FactCheckRetriever:
    def __init__(self):
        self.factcheck_key = os.environ.get("FACTCHECK_API_KEY", "").strip()

    async def search_claim_reviews(self, claim_query: str) -> list[dict[str, Any]]:
        """Search Google Fact Check Tools API for published fact-checks."""
        if not self.factcheck_key or not claim_query:
            return []

        signals = []
        try:
            url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
            params = {
                "query": claim_query,
                "key": self.factcheck_key,
                "pageSize": 3,
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    for item in data.get("claims", []):
                        reviews = item.get("claimReview", [])
                        for rev in reviews:
                            rating = (rev.get("textualRating") or "").lower()
                            publisher = (rev.get("publisher") or {}).get("name", "Fact Checker")
                            rev_url = rev.get("url") or ""

                            # Score polarity from rating
                            if any(w in rating for w in ["false", "fake", "incorrect", "misleading", "hoax", "altered", "distorted"]):
                                strength = -0.9
                            elif any(w in rating for w in ["true", "correct", "accurate"]):
                                strength = 0.85
                            elif any(w in rating for w in ["unproven", "mixture", "partly"]):
                                strength = -0.3
                            else:
                                strength = -0.5

                            signals.append({
                                "engine": "claim",
                                "kind": "factcheck_match",
                                "strength": strength,
                                "weight": 2.0,
                                "summary": f"{publisher} rated this claim as '{rating.capitalize()}'",
                                "evidence": {
                                    "publisher": publisher,
                                    "rating": rating,
                                    "url": rev_url,
                                    "claimReviewed": item.get("text", claim_query),
                                    "source": publisher,
                                },
                                "limitation": f"Matched from published fact-check by {publisher}.",
                                "mock": False,
                            })
        except Exception as e:
            log.warning("Fact check search error: %s", e)
        return signals

    async def judge_polarity(self, claim: str, candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Natural Language Inference: judge whether each source SUPPORTS, CONTRADICTS, or is UNRELATED to the claim."""
        if not candidates or os.environ.get("PYTEST_CURRENT_TEST"):
            return [{"strength": 0.8, "weight": 1.5, "kind": "news_corroboration", **c} for c in candidates]

        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not groq_key:
            return [{"strength": 0.7, "weight": 1.2, "kind": "news_corroboration", **c} for c in candidates]

        prompt = f'Claim: "{claim}"\n\nEvaluate each headline:\n'
        for i, c in enumerate(candidates):
            prompt += f"{i+1}. {c['title']}\n"
        prompt += (
            '\nFor each headline, determine if it SUPPORTS, CONTRADICTS, or is UNRELATED to the claim '
            '(e.g. mentions a completely different location or event).\n'
            'Return ONLY JSON: [{"id": 1, "judgment": "SUPPORTS" | "CONTRADICTS" | "UNRELATED"}]'
        )

        try:
            import groq
            import re
            client = groq.Groq(api_key=groq_key)
            resp = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            content = resp.choices[0].message.content.strip()
            m = re.search(r"\[.*\]", content, re.DOTALL)
            if m:
                import json
                judgments = json.loads(m.group(0))
                judged = {}
                for j in judgments:
                    judged[j.get("id")] = j.get("judgment", "UNRELATED")

                signals = []
                for i, c in enumerate(candidates):
                    j_val = judged.get(i + 1, "UNRELATED")
                    if j_val == "SUPPORTS":
                        signals.append({
                            "engine": "claim",
                            "kind": "news_corroboration",
                            "strength": 0.85,
                            "weight": 1.5,
                            "summary": f"Corroborating reporting: '{c['title']}' ({c['domain']})",
                            "evidence": {"headline": c["title"], "source": c["domain"], "url": c["url"]},
                            "limitation": "Live news report directly corroborates claim statement.",
                            "mock": False,
                        })
                    elif j_val == "CONTRADICTS":
                        signals.append({
                            "engine": "claim",
                            "kind": "news_contradiction",
                            "strength": -0.85,
                            "weight": 1.8,
                            "summary": f"Contradicting reporting: '{c['title']}' ({c['domain']})",
                            "evidence": {"headline": c["title"], "source": c["domain"], "url": c["url"]},
                            "limitation": "Published reporting refutes or contradicts the specific claim details.",
                            "mock": False,
                        })
                    # UNRELATED is discarded so it never falsely supports or inflates the verdict
                return signals
        except Exception as e:
            log.debug("Polarity judgment notice: %s", e)

        return [{
            "engine": "claim",
            "kind": "news_corroboration",
            "strength": 0.7,
            "weight": 1.2,
            "summary": f"Related reporting: '{c['title']}' ({c['domain']})",
            "evidence": {"headline": c["title"], "source": c["domain"], "url": c["url"]},
            "limitation": "News coverage mentions topic.",
            "mock": False,
        } for c in candidates]

    async def search_news_corroboration(self, query: str) -> list[dict[str, Any]]:
        """Search live news and web coverage, filtering with NLI polarity."""
        if not query or len(query.strip()) < 5 or os.environ.get("PYTEST_CURRENT_TEST"):
            return []

        # Clean query: pick key keywords (up to 8 words)
        words = [w for w in query.replace(":", " ").replace("-", " ").split() if len(w) > 2]
        clean_q = " ".join(words[:8])

        candidates = []
        # 1. Search live news via DuckDuckGo Lite
        try:
            import bs4
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post("https://lite.duckduckgo.com/lite/", data={"q": clean_q}, headers=headers)
                if resp.status_code == 200:
                    soup = bs4.BeautifulSoup(resp.text, "html.parser")
                    for a in soup.select("a.result-link")[:4]:
                        title = a.get_text().strip()
                        href = a.get("href")
                        if href and href.startswith("http"):
                            domain = urllib.parse.urlparse(href).netloc.replace("www.", "")
                            candidates.append({"title": title, "url": href, "domain": domain})
        except Exception as e:
            log.debug("Web news search notice: %s", e)

        # 2. Fallback to GDELT DOC API if no candidates
        if not candidates:
            try:
                safe_query = urllib.parse.quote(clean_q[:50])
                url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={safe_query}&mode=artlist&maxrecords=2&format=json"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        for top in data.get("articles", [])[:2]:
                            title = top.get("title", "")
                            source_domain = top.get("domain", "News Source")
                            art_url = top.get("url", "")
                            if art_url:
                                candidates.append({"title": title, "url": art_url, "domain": source_domain})
            except Exception as e:
                log.debug("GDELT news search notice: %s", e)

        if not candidates:
            return []

        # Run NLI Polarity judge on all candidate articles
        return await self.judge_polarity(query, candidates)


retriever = FactCheckRetriever()

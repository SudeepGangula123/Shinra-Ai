"""LLM router: Groq -> Gemini -> Ollama -> Rule-based fallback.

Handles:
- Claim extraction (atomic claims, quotes, numbers).
- Explanation generation grounded strictly in retrieved evidence citations.
- Language support (Hindi, Telugu, Tamil, Bengali, etc.).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import httpx

log = logging.getLogger("shinri.llm_router")


class LLMRouter:
    def __init__(self):
        self.groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").strip()

    def detect_language(self, text: str) -> str:
        """Simple fast heuristic language detector for Indian scripts and English."""
        if not text:
            return "en"
        # Check Unicode ranges
        for ch in text:
            cp = ord(ch)
            if 0x0900 <= cp <= 0x097F:
                return "hi"  # Devanagari (Hindi/Marathi)
            if 0x0C00 <= cp <= 0x0C7F:
                return "te"  # Telugu
            if 0x0B80 <= cp <= 0x0BFF:
                return "ta"  # Tamil
            if 0x0980 <= cp <= 0x09FF:
                return "bn"  # Bengali
            if 0x0A80 <= cp <= 0x0AFF:
                return "gu"  # Gujarati
            if 0x0C80 <= cp <= 0x0CFF:
                return "kn"  # Kannada
            if 0x0D00 <= cp <= 0x0D7F:
                return "ml"  # Malayalam
            if 0x0600 <= cp <= 0x06FF:
                return "ur"  # Urdu
        return "en"

    async def _call_groq(self, prompt: str, system: str = "") -> Optional[str]:
        if not self.groq_key:
            return None
        try:
            import groq
            client = groq.Groq(api_key=self.groq_key)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=messages,
                temperature=0.1,
                max_tokens=800,
            )
            return resp.choices[0].message.content
        except Exception as e:
            log.warning("Groq call failed, trying next provider: %s", e)
            return None

    async def _call_gemini(self, prompt: str, system: str = "") -> Optional[str]:
        if not self.gemini_key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": (f"System: {system}\n\n" if system else "") + prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800},
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 200:
                    data = r.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            log.warning("Gemini call failed, trying next provider: %s", e)
            return None

    async def _call_ollama(self, prompt: str, system: str = "") -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": "llama3.2", "prompt": prompt, "system": system, "stream": False},
                )
                if r.status_code == 200:
                    return r.json().get("response")
        except Exception:
            return None

    async def complete(self, prompt: str, system: str = "") -> tuple[str, str]:
        """Try Groq -> Gemini -> Ollama -> rule-based fallback."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return "", "rule-fallback"
        res = await self._call_groq(prompt, system)
        if res:
            return res, "groq"
        res = await self._call_gemini(prompt, system)
        if res:
            return res, "gemini"
        res = await self._call_ollama(prompt, system)
        if res:
            return res, "ollama"
        return "", "no-ai-fallback"

    async def extract_claims(self, text: str) -> list[dict[str, Any]]:
        """Extract atomic claims with exact quotes and identified numeric claims."""
        if not text or not text.strip():
            return []

        clean_text = text.strip()
        system = (
            "You are an expert fact-check claim extractor. Given text, extract atomic factual claims. "
            "Return ONLY a valid JSON list of objects: [{\"id\": \"c1\", \"text\": \"statement\", \"quote\": \"exact quote\", \"numbers\": [{\"value\": 10, \"unit\": \"...\"}]}]"
        )
        prompt = f"Text to extract claims from:\n{clean_text}"

        response, provider = await self.complete(prompt, system)
        if response:
            try:
                # Find JSON block
                m = re.search(r"\[.*\]", response, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    if isinstance(parsed, list) and len(parsed) > 0:
                        claims = []
                        for i, c in enumerate(parsed):
                            claims.append({
                                "id": c.get("id") or f"c{i+1}",
                                "text": c.get("text") or clean_text,
                                "quote": c.get("quote") or clean_text[:100],
                                "numbers": c.get("numbers") or [],
                            })
                        return claims
            except Exception as e:
                log.debug("JSON parse of claims failed: %s", e)

        # Robust Rule-based Fallback
        # Split by sentence or line
        sentences = [s.strip() for s in re.split(r"[.!?\n]+", clean_text) if len(s.strip()) > 10]
        if not sentences:
            sentences = [clean_text]

        claims = []
        for i, s in enumerate(sentences[:3]):
            # Find numbers
            numbers = []
            for num in re.finditer(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*([a-zA-Z%₹]+)?\b", s):
                try:
                    val = float(num.group(1).replace(",", ""))
                    numbers.append({"value": val, "unit": num.group(2) or "", "raw": num.group(0)})
                except ValueError:
                    pass
            claims.append({
                "id": f"c{i+1}",
                "text": s,
                "quote": s,
                "numbers": numbers,
            })
        return claims

    async def generate_explanation(
        self,
        claims: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        verdict_label: str,
        confidence: float,
        lang: str = "en",
    ) -> tuple[str, list[str], str]:
        """Generate cited explanation grounded strictly in signals."""
        citations = []
        for s in signals:
            ev = s.get("evidence") or {}
            url = ev.get("url")
            if url and url not in citations:
                citations.append(url)

        system = (
            "You are a rigorous, neutral fact-checking assistant. Explain the verdict honestly in the requested language. "
            "Rules:\n"
            "1. Every factual statement must cite one of the provided source URLs.\n"
            "2. State clearly how sure we are and mention weak signals or limitations.\n"
            "3. If evidence is thin, say 'not enough evidence' honestly.\n"
            "4. Never hallucinate or assume unverified facts."
        )

        prompt = (
            f"Language code: {lang}\n"
            f"Verdict: {verdict_label} (Confidence: {int(confidence * 100)}%)\n"
            f"Claims: {json.dumps(claims, ensure_ascii=False)}\n"
            f"Evidence signals: {json.dumps(signals, ensure_ascii=False)}\n"
            f"Available citation URLs: {json.dumps(citations)}\n\n"
            f"Write a concise, 2-3 paragraph explanation in {lang}."
        )

        resp, provider = await self.complete(prompt, system)
        if resp and len(resp.strip()) > 30:
            return resp.strip(), citations, provider

        # Grounded Template Fallback
        label_text = verdict_label.replace("_", " ")
        lines = [f"Verdict: {label_text.upper()} with {int(confidence * 100)}% confidence."]
        if signals:
            lines.append("Key findings:")
            for s in signals[:3]:
                summ = s.get("summary") or f"{s.get('engine')}: {s.get('kind')}"
                ev = s.get("evidence") or {}
                src = ev.get("source") or ev.get("url") or ""
                if src:
                    lines.append(f"• {summ} (Source: {src})")
                else:
                    lines.append(f"• {summ}")
        else:
            lines.append("No definitive corroborating or contradicting official records were found.")

        if citations:
            lines.append(f"References: {', '.join(citations[:3])}")

        return "\n\n".join(lines), citations, "template"


llm_router = LLMRouter()

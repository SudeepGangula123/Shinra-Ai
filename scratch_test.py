import json
import os
import re
from dotenv import load_dotenv
import groq

load_dotenv()
c = groq.Groq()

def judge_evidence_polarity(claim: str, items: list[dict]) -> list[dict]:
    if not items:
        return []
    prompt = f"""You are a Natural Language Inference (NLI) judge.
Claim: "{claim}"

Evaluate each retrieved headline/snippet:
"""
    for i, item in enumerate(items):
        prompt += f"{i+1}. {item.get('title')}\n"

    prompt += """
For each item, determine:
- SUPPORTS: The source clearly confirms the specific claim (same person/subject, action, location, and key numbers).
- CONTRADICTS: The source directly refutes or contradicts the specific claim.
- UNRELATED: The source is about a different topic, different location, or different event.

Return ONLY a JSON list:
[{"id": 1, "judgment": "SUPPORTS" | "CONTRADICTS" | "UNRELATED"}]
"""
    try:
        resp = c.chat.completions.create(model='openai/gpt-oss-20b', messages=[{'role':'user', 'content':prompt}], temperature=0.0)
        content = resp.choices[0].message.content.strip()
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if m:
            judgments = json.loads(m.group(0))
            for j in judgments:
                idx = j.get("id", 1) - 1
                if 0 <= idx < len(items):
                    items[idx]["judgment"] = j.get("judgment", "UNRELATED")
    except Exception as e:
        print("Error:", e)
    return items

test_claim = "Prime Minister Narendra Modi launched developmental projects worth over ₹14,000 crore in Gujarat"
test_items = [
    {"title": "PM Modi inaugurates five projects worth Rs 3,350 crore in Ladakh"},
    {"title": "PM Modi launches Rs 14,000 crore development projects in Gujarat"},
]

res = judge_evidence_polarity(test_claim, test_items)
print(res)

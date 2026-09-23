"""
The AI brain: reads each opportunity and decides
  1. is this a REAL person trying to hire/find someone (not an essay/ad/spam)?
  2. how well does it fit MY offer? (0-10)
  3. drafts a short, specific, non-salesy first message.

Uses OpenRouter with a cheap model, scored concurrently for speed.
"""
import os
import json
import concurrent.futures as cf
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()
_CFG = yaml.safe_load(open("config.yaml", encoding="utf-8"))
OFFER = _CFG["offer"]
MODEL = os.getenv("BRAIN_MODEL", "openai/gpt-4o-mini")

_PROMPT = """You qualify leads for a freelancer. Decide if a web post is a real
opportunity to get hired, and how well it fits.

FREELANCER:
- Does: {what}
- Ideal client: {ideal}
- Wants engagement type: {engagement}   (e.g. freelance / contract / part-time)

POST:
Source: {source}
{text}

Return STRICT JSON only:
{{"is_opportunity": true/false,   // true only if someone is looking to hire / needs a service. false for essays, news, self-promo, job-seekers, generic discussion.
  "engagement": "freelance|contract|part-time|full-time|unclear",  // what THIS post offers
  "score": 0-10,                  // fit of SKILLS *and* ENGAGEMENT. If the freelancer wants freelance/contract but this post is a full-time permanent employee role with no contract/freelance option, score 3 or below. 0 if not an opportunity.
  "reason": "<8 words why>",
  "draft": "<=45 word first message to send them, specific to their post, friendly, no fluff, no 'I hope this finds you well'>"}}"""


def derive_profile(profile_text):
    """Turn a free-text profile ('I'm an AI engineer... looking for freelance work')
    into search terms + a structured offer used for scoring and drafting."""
    key = os.getenv("OPENROUTER_API_KEY")
    fallback = {"terms": [profile_text[:40]],
                "what_i_do": profile_text, "ideal_customer": "anyone hiring for this"}
    if not key:
        return fallback
    prompt = f"""A freelancer describes themselves and what they want:
"{profile_text}"

Return STRICT JSON to help find them work:
{{"terms": [3-5 short search keywords buyers would use, e.g. "AI engineer","chatbot","automation"],
  "what_i_do": "<one crisp sentence describing their service>",
  "ideal_customer": "<who would hire them>",
  "engagement": "<what they want: freelance, contract, part-time, full-time, or 'any' if unstated>"}}"""
    fallback["engagement"] = "any"
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                                "response_format": {"type": "json_object"}, "max_tokens": 250},
                          timeout=45)
        r.raise_for_status()
        d = json.loads(r.json()["choices"][0]["message"]["content"])
        terms = [t for t in d.get("terms", []) if t][:5] or fallback["terms"]
        return {"terms": terms,
                "what_i_do": d.get("what_i_do") or profile_text,
                "ideal_customer": d.get("ideal_customer") or "anyone hiring for this",
                "engagement": d.get("engagement") or "any"}
    except Exception:
        return fallback


def score_one(item, offer=None):
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {"is_opportunity": True, "score": 0, "reason": "no LLM key", "draft": ""}
    off = offer or OFFER
    prompt = _PROMPT.format(
        what=str(off.get("what_i_do", "")).strip(), ideal=str(off.get("ideal_customer", "")).strip(),
        engagement=str(off.get("engagement", "any")),
        source=item.get("source", ""), text=(item.get("title", "") + "\n" + item.get("text", ""))[:1400])
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}, "max_tokens": 200,
                  "temperature": 0.3},
            timeout=45,
        )
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        return {
            "is_opportunity": bool(data.get("is_opportunity", False)),
            "engagement": str(data.get("engagement", "unclear")),
            "score": int(data.get("score", 0) or 0),
            "reason": str(data.get("reason", ""))[:80],
            "draft": str(data.get("draft", "")),
        }
    except Exception as e:
        return {"is_opportunity": True, "score": 0, "reason": f"ai error", "draft": ""}


def score_all(items, min_score=5, max_workers=16, offer=None):
    """Score items concurrently; keep only real opportunities >= min_score, ranked."""
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(lambda it: score_one(it, offer), items))
    kept = []
    for it, res in zip(items, results):
        it.update(res)
        if res["is_opportunity"] and res["score"] >= min_score:
            kept.append(it)
    kept.sort(key=lambda x: x.get("score", 0), reverse=True)
    return kept

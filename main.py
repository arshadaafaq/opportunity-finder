"""
Opportunity Finder v1 — the "find the right customer at the right moment" brain.

Watches free public sources for buying-intent signals, uses an LLM to score how
well each matches YOUR offer, finds the poster, and drafts a reply.

No LinkedIn login, no scraping of your own account. Reddit's public JSON only.

Run:  python main.py
Needs: pip install -r requirements.txt   and  a .env with OPENROUTER_API_KEY=...
"""
import os
import json
import time
import datetime as dt
import urllib.parse

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()
CFG = yaml.safe_load(open("config.yaml", encoding="utf-8"))
UA = {"User-Agent": "opportunity-finder/0.1 (personal lead research)"}


def fetch_reddit(cfg):
    """Pull recent posts matching buying-intent queries. Public JSON, no auth."""
    rc = cfg["sources"]["reddit"]
    if not rc.get("enabled"):
        return []
    cutoff = time.time() - rc["hours_back"] * 3600
    subs = "+".join(rc["subreddits"])
    seen, items = set(), []
    for q in rc["queries"]:
        url = (
            f"https://www.reddit.com/r/{subs}/search.json?"
            + urllib.parse.urlencode(
                {"q": q, "restrict_sr": "on", "sort": "new",
                 "limit": rc["max_per_query"], "t": "week"}
            )
        )
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            children = r.json().get("data", {}).get("children", [])
        except Exception as e:
            print(f"  ! reddit query '{q}' failed: {e}")
            continue
        for c in children:
            d = c["data"]
            if d["id"] in seen or d["created_utc"] < cutoff:
                continue
            seen.add(d["id"])
            items.append({
                "source": f"reddit/r/{d['subreddit']}",
                "title": d["title"],
                "text": (d.get("selftext") or "")[:1500],
                "author": d["author"],
                "url": "https://reddit.com" + d["permalink"],
                "posted": dt.datetime.utcfromtimestamp(d["created_utc"]).isoformat() + "Z",
            })
        time.sleep(1)  # be polite
    print(f"  found {len(items)} candidate posts")
    return items


def score_and_draft(item, cfg):
    """Ask the LLM: is this a real buying signal for MY offer? Score + draft a reply."""
    key = os.getenv("OPENROUTER_API_KEY")
    offer = cfg["offer"]
    prompt = f"""You are a lead-qualification analyst for a freelance AI engineer.

MY OFFER:
- What I do: {offer['what_i_do']}
- Ideal customer: {offer['ideal_customer']}
- Location focus: {offer['location_focus']}

A POST I FOUND:
Source: {item['source']}
Title: {item['title']}
Body: {item['text']}

Decide if this is a real person/company expressing a NEED I could get paid to solve
(not someone selling services, not a generic discussion). Respond as strict JSON:
{{"score": 0-10 how strong+relevant the buying intent is,
  "reason": "one line why",
  "who": "who the buyer is",
  "draft": "a short, specific, non-salesy first reply I could send (<=60 words)"}}"""

    if not key:
        # No LLM key yet: fall back to a keyword heuristic so you can still see it run.
        text = (item["title"] + " " + item["text"]).lower()
        hit = sum(w in text for w in
                  ["looking for", "need", "hire", "build", "automate", "chatbot", "ai "])
        return {"score": min(hit * 2, 10), "reason": "keyword match (no LLM key set)",
                "who": item["author"], "draft": "(set OPENROUTER_API_KEY to get AI drafts)"}

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": cfg["llm"]["model"],
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
            timeout=60,
        )
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"score": 0, "reason": f"llm error: {e}", "who": item["author"], "draft": ""}


def main():
    print("Opportunity Finder v1")
    print("Fetching signals...")
    items = fetch_reddit(CFG)

    print("Scoring with AI brain...")
    scored = []
    for it in items:
        res = score_and_draft(it, CFG)
        it.update(res)
        scored.append(it)

    keep = [x for x in scored if x.get("score", 0) >= CFG["llm"]["min_score"]]
    keep.sort(key=lambda x: x["score"], reverse=True)

    out = CFG["output"]["file"]
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Opportunities — {dt.date.today()}\n\n")
        f.write(f"{len(keep)} qualified out of {len(scored)} scanned.\n\n")
        for x in keep:
            f.write(f"## [{x['score']}/10] {x['title']}\n")
            f.write(f"- **Who:** {x.get('who','?')}  \n")
            f.write(f"- **Why:** {x.get('reason','')}  \n")
            f.write(f"- **Source:** {x['source']} · {x['posted']}  \n")
            f.write(f"- **Link:** {x['url']}  \n")
            f.write(f"- **Draft reply:** {x.get('draft','')}\n\n")
    print(f"\nDone. {len(keep)} qualified opportunities -> {out}")


if __name__ == "__main__":
    main()

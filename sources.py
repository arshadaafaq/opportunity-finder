"""
Phase 1 data layer: fetch opportunity posts from FREE, no-key sources.
Proves the platform's core: user searches -> we return live opportunities.

Sources here (no API key needed):
  - Hacker News (Algolia API): "Who is hiring" + any hiring/freelance mentions
  - RemoteOK: remote job posts (companies hiring = potential clients)

Later we add: Reddit API, LinkedIn (Apify), Google (Serper).
"""
import time
import requests
import datetime as dt
from dotenv import load_dotenv

load_dotenv()

UA = {"User-Agent": "Mozilla/5.0 (opportunity-finder; personal lead research)"}

# simple in-memory cache: {key: (timestamp, data)}
_CACHE = {}
_TTL = 600  # 10 min


def _cache_get(key):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    return None


def _cache_set(key, data):
    _CACHE[key] = (time.time(), data)


def _matches(text, query):
    """True if ANY word of the query appears (so 'AI automation' -> AI OR automation)."""
    t = text.lower()
    return any(w in t for w in query.lower().split())


def extract_contacts(text):
    """Pull emails + phone numbers from post text, including common obfuscations
    like 'name at company dot com'. Returns {'emails':[...], 'phones':[...]}."""
    import re
    if not text:
        return {"emails": [], "phones": []}
    t = text

    # de-obfuscate: "x at y dot com" / "x [at] y [dot] com"
    deob = re.sub(r"\s*[\[\(]?\s*at\s*[\]\)]?\s*", "@", t, flags=re.I)
    deob = re.sub(r"\s*[\[\(]?\s*dot\s*[\]\)]?\s*", ".", deob, flags=re.I)

    emails = set()
    for src in (t, deob):
        for m in re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", src):
            if not m.lower().endswith((".png", ".jpg", ".gif")):
                emails.add(m.strip(".,;:"))

    # phones: international / US / India formats, 8-15 digits with separators
    phones = set()
    for m in re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", t):
        digits = re.sub(r"\D", "", m)
        if 8 <= len(digits) <= 15:
            phones.add(m.strip())

    return {"emails": sorted(emails), "phones": sorted(phones)}


def _age(ts):
    days = (dt.datetime.utcnow() - dt.datetime.utcfromtimestamp(ts)).days
    return "today" if days == 0 else f"{days}d ago"


def _clean(html):
    import re
    html = (html or "").replace("<p>", "\n").replace("&#x2F;", "/").replace("&#x27;", "'")
    html = html.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&").replace("&quot;", '"')
    return re.sub(r"<[^>]+>", "", html).strip()


def _latest_hiring_thread(kind):
    """Find the newest monthly HN thread posted by the 'whoishiring' bot.
    kind='hiring' -> 'Who is hiring?'; kind='freelance' -> 'Freelancer? Seeking freelancer?'"""
    q = "Who is hiring" if kind == "hiring" else "Freelancer Seeking freelancer"
    # search_by_date => newest first, so we get the CURRENT month's thread
    r = requests.get("http://hn.algolia.com/api/v1/search_by_date",
                     params={"query": q, "tags": "story,author_whoishiring",
                             "hitsPerPage": 3}, headers=UA, timeout=20)
    hits = r.json().get("hits", [])
    return hits[0]["objectID"] if hits else None


def _hn_thread_comments(kind):
    """All comments of the latest hiring thread, cached for 10 min."""
    ck = f"hn_{kind}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    thread_id = _latest_hiring_thread(kind)
    if not thread_id:
        return []
    r = requests.get("http://hn.algolia.com/api/v1/search",
                     params={"tags": f"comment,story_{thread_id}",
                             "hitsPerPage": 400}, headers=UA, timeout=20)
    hits = r.json().get("hits", [])
    _cache_set(ck, hits)
    return hits


def from_hackernews(query, limit=25):
    """Pull real job posts from HN's monthly 'Who is hiring' + 'Seeking freelancer'
    threads, filtered to the user's query. Each top-level comment = one opportunity."""
    out = []
    for kind in ("hiring", "freelance"):
        try:
            for h in _hn_thread_comments(kind):
                text = _clean(h.get("comment_text"))
                if len(text) < 40 or not _matches(text, query):
                    continue
                first = text.split("\n")[0][:120]
                out.append({
                    "source": "HN " + ("Who is hiring" if kind == "hiring" else "Freelance"),
                    "title": first,
                    "text": text[:1200],
                    "author": h.get("author", "?"),
                    "url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                    "posted": _age(h.get("created_at_i", 0)),
                    "ts": h.get("created_at_i", 0),
                })
                if len(out) >= limit:
                    break
        except Exception as e:
            print(f"  ! HN {kind} error: {e}")
    return out


def from_remoteok(query, limit=20):
    """RemoteOK public JSON. Filter jobs by query (company hiring = a lead)."""
    out = []
    try:
        rows = _cache_get("remoteok")
        if rows is None:
            r = requests.get("https://remoteok.com/api", headers=UA, timeout=20)
            r.raise_for_status()
            rows = r.json()[1:]  # first item is metadata/legal
            _cache_set("remoteok", rows)
        for j in rows:
            blob = (j.get("position", "") + " " + " ".join(j.get("tags", [])) + " "
                    + j.get("description", ""))
            if not _matches(blob, query):
                continue
            ts = 0
            try:
                ts = int(dt.datetime.fromisoformat(j.get("date", "")).timestamp())
            except Exception:
                pass
            out.append({
                "source": "RemoteOK",
                "title": f"{j.get('company','?')} is hiring: {j.get('position','')}",
                "text": _clean(j.get("description"))[:600],
                "author": j.get("company", "?"),
                "url": j.get("url", ""),
                "posted": _age(ts) if ts else (j.get("date", "")[:10]),
                "ts": ts,
            })
            if len(out) >= limit:
                break
    except Exception as e:
        print(f"  ! RemoteOK error: {e}")
    return out


def from_linkedin_jobs(query, limit=25):
    """LinkedIn public 'jobs guest' endpoint — the listings LinkedIn shows to
    logged-out visitors. No account, no cookies. A company hiring = a warm lead."""
    from bs4 import BeautifulSoup
    ck = "li_" + query.lower()
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    out = []
    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    browser_ua = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")}
    try:
        r = requests.get(url, params={"keywords": query, "location": "", "start": 0},
                         headers=browser_ua, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("li")[:limit]:
            title = card.select_one("h3.base-search-card__title")
            company = card.select_one("h4.base-search-card__subtitle")
            loc = card.select_one(".job-search-card__location")
            link = card.select_one("a.base-card__full-link")
            date_el = card.select_one("time")
            if not (title and link):
                continue
            posted_iso = date_el.get("datetime", "") if date_el else ""
            ts = 0
            try:
                ts = int(dt.datetime.fromisoformat(posted_iso).timestamp())
            except Exception:
                pass
            out.append({
                "source": "LinkedIn",
                "title": f"{company.get_text(strip=True) if company else '?'} is hiring: "
                         f"{title.get_text(strip=True)}",
                "text": (loc.get_text(strip=True) if loc else "") + " — via LinkedIn Jobs",
                "author": company.get_text(strip=True) if company else "?",
                "url": link.get("href", "").split("?")[0],
                "posted": _age(ts) if ts else (posted_iso[:10] or "recent"),
                "ts": ts,
            })
    except Exception as e:
        print(f"  ! LinkedIn error: {e}")
    _cache_set(ck, out)
    return out


def from_linkedin_posts(query, limit=50):
    """LinkedIn POSTS where people say they're looking for someone.
    Uses the Apify 'harvestapi/linkedin-post-search' actor to get FULL post content
    (where people sometimes write their email/phone). No account, no cookies.
    Needs APIFY_TOKEN in .env. Costs ~$0.002/post, so we cache aggressively.
    Returns [] quietly if no token."""
    import os
    tok = os.getenv("APIFY_TOKEN")
    if not tok:
        return []
    ck = f"lip_{limit}_{query.lower()}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    out = []
    url = ("https://api.apify.com/v2/acts/harvestapi~linkedin-post-search/"
           f"run-sync-get-dataset-items?token={tok}")
    # several intent phrasings to capture more real opportunities;
    # maxPosts is PER query, so divide so the total ~= limit
    queries = [f"looking for {query}", f"hiring {query}", f"need {query}",
               f"seeking {query}"]
    per_q = max(5, limit // len(queries))
    payload = {"searchQueries": queries, "maxPosts": per_q}
    seen = set()
    try:
        r = requests.post(url, json=payload, timeout=300)
        r.raise_for_status()
        for p in r.json():
            u = p.get("linkedinUrl") or p.get("shareLinkedinUrl") or ""
            if u in seen:
                continue
            seen.add(u)
            a = p.get("author") or {}
            name = (a.get("name")
                    or f"{a.get('firstName','')} {a.get('lastName','')}").strip() or "?"
            content = p.get("content", "") or ""
            first = content.split("\n")[0][:120] or "LinkedIn post"
            ts = 0
            posted = p.get("postedAt")
            if isinstance(posted, dict):
                ts = int(posted.get("timestamp", 0) or 0) // 1000
            out.append({
                "source": "LinkedIn Post",
                "title": f"{name}: {first}",
                "text": content[:1500],
                "author": name,
                "url": p.get("linkedinUrl") or p.get("shareLinkedinUrl") or "",
                "posted": _age(ts) if ts else "recent",
                "ts": ts,
                "profile": (a.get("linkedinUrl") or a.get("url") or ""),
            })
    except Exception as e:
        print(f"  ! LinkedIn posts (Apify) error: {e}")
    _cache_set(ck, out)
    return out


def fetch_all(query):
    print(f"Searching for: '{query}'")
    items = (from_hackernews(query) + from_remoteok(query)
             + from_linkedin_jobs(query) + from_linkedin_posts(query))
    print(f"  {len(items)} raw opportunities found\n")
    return items


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "AI"
    for i, it in enumerate(fetch_all(q)[:15], 1):
        print(f"{i}. [{it['source']} · {it['posted']}] {it['title']}")
        print(f"   by {it['author']} — {it['url']}")

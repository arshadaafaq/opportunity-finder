# Client Radar

**An AI agent that finds freelance/client opportunities across the web, ranks them to your profile, extracts the hiring contact, and drafts your outreach — from a single sentence about yourself.**

You describe yourself in plain English ("I'm an AI engineer looking for freelance projects") and Client Radar does the rest: it figures out what to search for, pulls live opportunities from multiple sources, uses an LLM to keep only the real, well-fitting ones, extracts emails where present, and writes a tailored first message for each.

## What it does

1. **Understands your profile** — an LLM turns free text into search terms + your offer + desired engagement (freelance / contract / full-time).
2. **Aggregates opportunities** from several sources in one search:
   - **LinkedIn Jobs** — public jobs guest endpoint (no login)
   - **LinkedIn Posts** — "looking for a freelancer" posts via the Apify post-search actor
   - **Hacker News** — the monthly "Who is hiring?" and "Freelancer? Seeking freelancer?" threads
   - **RemoteOK** — remote job postings
3. **Extracts contacts** — pulls emails/phones from post text (handles "name at company dot com" obfuscation), builds a DM list for the rest.
4. **AI ranking + drafting** — scores each post for skill *and* engagement fit, filters out noise (essays, ads, job-seekers), and drafts a short, specific outreach message per lead.
5. **Delivers** a clean, filterable web UI with a "copy all emails" action.

## Architecture

```
profile ──▶ brain.derive_profile()   (LLM: terms + offer + engagement)
        ──▶ sources.*                 (fetch: LinkedIn, HN, RemoteOK)
        ──▶ sources.extract_contacts  (regex: emails / phones)
        ──▶ brain.score_all()         (LLM, concurrent: filter + rank + draft)
        ──▶ FastAPI  /find            (JSON) ──▶ web UI
```

- `app.py` — FastAPI server + single-page UI
- `sources.py` — data sources, caching, contact extraction
- `brain.py` — the LLM layer (profile understanding, scoring, drafting)

## Tech stack

Python · FastAPI · OpenRouter (LLM) · Apify (LinkedIn scraping) · BeautifulSoup · concurrent scoring

## Run it

```bash
pip install -r requirements.txt

# create a .env file:
#   OPENROUTER_API_KEY=...        (required for AI ranking + drafting)
#   APIFY_TOKEN=...               (optional, for LinkedIn post scraping)

uvicorn app:app --port 8000
# open http://localhost:8000
```

The free sources (Hacker News, RemoteOK, LinkedIn Jobs) need no keys. LinkedIn post
scraping and AI ranking use the keys above.

## Notes

- Built as a personal tool to find AI/automation freelance work, designed to generalize to any freelancer.
- Respects source boundaries: no logged-in LinkedIn scraping; discovery is done via public endpoints and a third-party scraping API.
- Caching keeps repeat searches fast and API costs low.

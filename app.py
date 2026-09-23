"""
Client Radar — profile-first opportunity finder.
Describe yourself + what you want -> we fetch opportunities across the web,
score them to your profile, extract emails, and draft outreach.

Run:  uvicorn app:app --port 8000    then open http://localhost:8000
"""
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import sources
import brain

app = FastAPI(title="Client Radar")

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Client Radar</title>
<style>
  :root { --bg:#f6f8fb; --card:#fff; --line:#e3e8ef; --text:#1a2233; --muted:#68738a;
          --accent:#2563eb; --accent-weak:#eef3ff; --tag:#eef1f6; --violet:#7c3aed; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:34px 16px 4px; text-align:center; }
  h1 { margin:0 0 4px; font-size:28px; letter-spacing:-.3px; }
  .sub { color:var(--muted); font-size:14px; }
  .bar { max-width:760px; margin:20px auto 6px; padding:0 16px; }
  textarea { width:100%; padding:14px 16px; border-radius:12px; border:1px solid var(--line);
             background:var(--card); font-size:16px; font-family:inherit; resize:vertical;
             min-height:64px; outline:none; color:var(--text); }
  textarea:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-weak); }
  .row { display:flex; gap:12px; align-items:center; margin-top:10px; flex-wrap:wrap; }
  button { padding:13px 22px; border:0; border-radius:10px; background:var(--violet);
           color:#fff; font-size:16px; font-weight:600; cursor:pointer; }
  label.opt { font-size:13px; color:var(--muted); display:flex; gap:6px; align-items:center; }
  select { padding:8px 10px; border-radius:8px; border:1px solid var(--line);
           background:var(--card); font-size:13px; }
  #results { max-width:760px; margin:0 auto; padding:8px 16px 60px; }
  .understood { max-width:760px; margin:10px auto 0; padding:10px 14px; background:#eef2ff;
                border:1px solid #c7d2fe; border-radius:10px; font-size:13px; color:#3730a3; }
  .lead { max-width:760px; margin:12px auto 0; padding:12px 16px; background:#ecfdf3;
          border:1px solid #b7ebc6; border-radius:10px; font-size:14px; color:#166534; }
  .lead b { color:#065f46; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:16px 18px; margin:12px 0; box-shadow:0 1px 2px rgba(16,24,40,.04); }
  .card a.title { color:var(--accent); text-decoration:none; font-weight:600; font-size:16px;
                  line-height:1.35; display:inline-block; }
  .meta { color:var(--muted); font-size:12px; margin:8px 0; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .tag { background:var(--tag); padding:3px 9px; border-radius:6px; font-weight:500; }
  .tag.src { background:var(--accent-weak); color:var(--accent); }
  .score { background:var(--violet); color:#fff; font-weight:700; padding:3px 9px; border-radius:6px; }
  .reason { color:#6b7280; font-style:italic; }
  .snippet { color:#3d4658; font-size:14px; line-height:1.55; margin-top:4px;
             white-space:pre-wrap; max-height:96px; overflow:hidden; }
  .contact { margin:8px 0 2px; font-size:14px; }
  .contact a { color:#059669; font-weight:600; text-decoration:none; }
  .contact.dm { color:var(--muted); } .contact.dm a { color:var(--accent); }
  .draft { margin-top:8px; background:#faf5ff; border:1px solid #e9d5ff; border-radius:8px;
           padding:10px 12px; font-size:13.5px; color:#4c1d95; white-space:pre-wrap; }
  .draft .dlabel { font-weight:700; color:var(--violet); font-size:11px; text-transform:uppercase;
                   letter-spacing:.4px; display:block; margin-bottom:3px; }
  .mini { padding:3px 10px; font-size:12px; border-radius:6px; background:#ede9fe;
          color:#5b21b6; border:1px solid #ddd6fe; margin-left:8px; cursor:pointer; font-weight:600; }
  .lead .mini { background:#e6f4ea; color:#166534; border-color:#b7ebc6; }
  .status { text-align:center; color:var(--muted); padding:28px; }
</style></head><body>
<header>
  <h1>Client Radar</h1>
  <div class="sub">Describe yourself and what you want. We find the opportunities and draft your outreach.</div>
</header>
<div class="bar">
  <textarea id="profile" placeholder="e.g. I am an AI engineer with 5 years of experience looking for freelancing projects">I am an AI engineer with 5 years of experience looking for freelancing projects</textarea>
  <div class="row">
    <button onclick="find()">Find opportunities &amp; draft outreach</button>
    <label class="opt"><input type="checkbox" id="linkedin"> include LinkedIn posts (paid scrape)</label>
    <label class="opt">count
      <select id="limit"><option value="25">25</option><option value="50" selected>50</option>
      <option value="100">100</option></select>
    </label>
  </div>
</div>
<div id="understood"></div>
<div id="leadbar"></div>
<div id="results"><div class="status">Describe yourself above and hit Find.</div></div>
<script>
let ALL = [];
function esc(s){ return (s||'').replace(/</g,'&lt;'); }

function card(it){
  const emails=(it.emails||[]), phones=(it.phones||[]);
  let contact = emails.length
    ? '<div class="contact">📧 '+emails.map(e=>`<a href="mailto:${e}">${e}</a>`).join(', ')
      +` <button class="mini" onclick="navigator.clipboard.writeText('${emails[0]}')">copy</button></div>`
    : (phones.length ? '<div class="contact">📞 '+phones.join(', ')+'</div>'
      : `<div class="contact dm">✋ No email — DM: <a href="${it.url}" target="_blank">${esc(it.author)}</a></div>`);
  const eng = it.engagement ? `<span class="tag" style="background:#fef3c7;color:#92400e">${esc(it.engagement)}</span>` : '';
  const badge = (it.score!==undefined) ? `<span class="score">${it.score}/10</span>${eng}<span class="reason">${esc(it.reason)}</span>` : '';
  const draft = it.draft ? `<div class="draft"><span class="dlabel">Suggested message
      <button class="mini" onclick='navigator.clipboard.writeText(${JSON.stringify(it.draft)})'>copy</button></span>${esc(it.draft)}</div>` : '';
  return `<div class="card">
      <a class="title" href="${it.url}" target="_blank">${esc(it.title)}</a>
      <div class="meta">${badge}<span class="tag src">${esc(it.source)}</span>
        <span class="tag">${esc(it.author)}</span><span>${esc(it.posted)}</span></div>
      ${contact}<div class="snippet">${esc(it.text)}</div>${draft}
    </div>`;
}

function render(){
  const withEmail = ALL.filter(x=>(x.emails||[]).length);
  const allEmails = [...new Set(withEmail.flatMap(x=>x.emails))];
  window._E = allEmails;
  document.getElementById('leadbar').innerHTML = ALL.length ? `<div class="lead">
      <b>${ALL.length}</b> matched opportunities · <b>${withEmail.length}</b> with a direct email
      <button class="mini" onclick="copyAll()">Copy all ${allEmails.length} emails</button></div>` : '';
  document.getElementById('results').innerHTML = ALL.length ? ALL.map(card).join('')
    : '<div class="status">No matching opportunities found. Try describing your skills differently.</div>';
}
function copyAll(){ navigator.clipboard.writeText((window._E||[]).join('\\n'));
  alert((window._E||[]).length+' emails copied'); }

async function find(){
  const profile = document.getElementById('profile').value.trim();
  if(!profile) return;
  const linkedin = document.getElementById('linkedin').checked ? 1 : 0;
  const limit = document.getElementById('limit').value;
  document.getElementById('understood').innerHTML=''; document.getElementById('leadbar').innerHTML='';
  document.getElementById('results').innerHTML='<div class="status">Reading your profile, searching the web, and drafting messages'
    +(linkedin?' (incl. paid LinkedIn scrape, ~1 min)':'')+'…</div>';
  try{
    const r = await fetch(`/find?profile=${encodeURIComponent(profile)}&linkedin=${linkedin}&limit=${limit}`);
    const d = await r.json();
    ALL = d.opportunities || [];
    document.getElementById('understood').innerHTML = `<div class="understood">
      <b>Understood:</b> ${esc(d.profile.what_i_do)} &nbsp;·&nbsp; <b>Wants:</b> ${esc(d.profile.engagement||'any')} work
      &nbsp;·&nbsp; <b>Searching:</b> ${d.profile.terms.map(esc).join(', ')} &nbsp;·&nbsp; scanned ${d.count_scanned} posts</div>`;
    render();
  }catch(e){ document.getElementById('results').innerHTML='<div class="status">Error: '+e+'</div>'; }
}
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        k = it.get("url") or it.get("title")
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


@app.get("/find")
def find(profile: str, linkedin: int = 0, limit: int = 50):
    """Full pipeline from a free-text profile."""
    prof = brain.derive_profile(profile)
    terms = prof["terms"][:3]

    items = []
    for t in terms:
        items += sources.from_hackernews(t) + sources.from_remoteok(t) + sources.from_linkedin_jobs(t)
    if linkedin:
        items += sources.from_linkedin_posts(terms[0], limit=limit)
    items = _dedupe(items)
    # score the most recent ~80 (keeps latency + LLM cost sane)
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    scanned = len(items)
    items = items[:50]

    for it in items:
        c = sources.extract_contacts(f"{it.get('title','')} {it.get('text','')}")
        it["emails"], it["phones"] = c["emails"], c["phones"]

    offer = {"what_i_do": prof["what_i_do"], "ideal_customer": prof["ideal_customer"],
             "engagement": prof.get("engagement", "any")}
    ranked = brain.score_all(items, min_score=5, offer=offer)
    return JSONResponse({"profile": prof, "count_scanned": scanned, "opportunities": ranked})

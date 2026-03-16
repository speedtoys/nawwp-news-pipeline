#!/usr/bin/env python3
import datetime as dt
import html
import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
from score_articles import evaluate_article

CONFIG_FILE = "rss_sources.json"
ARCHIVE_FILE = "archive.json"
DOCS_DIR = Path("docs")
OUTPUT_FILE = DOCS_DIR / "news.json"
INDEX_FILE = DOCS_DIR / "index.html"
FAVICON_FILE = DOCS_DIR / "favicon.svg"

MAX_CANDIDATES_PER_FEED = int(os.getenv("MAX_CANDIDATES_PER_FEED", "60"))
MAX_AI_REVIEWS_PER_RUN = int(os.getenv("MAX_AI_REVIEWS_PER_RUN", "220"))
KEEP_MIN_SCORE = float(os.getenv("KEEP_MIN_SCORE", "4.0"))
WINGS_MIN_SCORE = float(os.getenv("WINGS_MIN_SCORE", "2.5"))
FETCH_WORKERS = int(os.getenv("FETCH_WORKERS", "10"))
AI_WORKERS = int(os.getenv("AI_WORKERS", "4"))
IGNORE_SEEN = os.getenv("IGNORE_SEEN", "0").lower() in {"1","true","yes","y"}

IDENTITY = ["dei","diversity","equity","inclusion","anti-woke","woke","trans","transgender","pronoun","drag","pride","lgbt","lgbtq","book ban","banned books","library","school board","parents' rights","voucher","school choice","religious liberty","christian values","traditional values","western civilization","white people","white boys","young white men","muslim","islamic","muslim school","islamic school","immigrant","immigration","cair","sharia"]
OUTRAGE = ["backlash","outrage","criticized","criticizes","slams","targets","opposes","ban","bans","blocks","defund","exclude","excluded","remove","pull funding","lawsuit","sues","debate","hearing","boycott","pressure campaign"]
ACTORS = ["maga","trump","republican","republicans","gop","conservative","conservatives","fox news","moms for liberty","charlie kirk","erika kirk","governor","attorney general","state lawmakers","christian nationalist"]
CRIME = ["shooting","murder","bombing","terror","arrested","charged with","indicted","convicted","sentenced","assault","rape","sexual assault","trafficking","abuse","homicide","stabbing"]
SCANDAL = ["fake electors","alternate electors","electors","election fraud","campaign finance","bribery","corruption","indictment","prosecution","felony","embezzlement"]

def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()

def normalize_url(url):
    url = (url or "").strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url

def build_google_news_rss(query):
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}+when:30d&hl=en-US&gl=US&ceid=US:en"

def parse_date(entry):
    for raw in [getattr(entry, "published", None), getattr(entry, "updated", None), getattr(entry, "created", None)]:
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(dt.timezone.utc).isoformat()
            except Exception:
                pass
    return dt.datetime.now(dt.timezone.utc).isoformat()

def load_feed_specs():
    cfg = load_json(CONFIG_FILE, {})
    out = []
    for item in cfg.get("rss_feeds", []):
        if item.get("enabled", True):
            out.append({"label": item["label"], "url": item["url"], "state": item.get("state")})
    for item in cfg.get("google_news_queries", []):
        if item.get("enabled", True):
            out.append({"label": item["label"], "url": build_google_news_rss(item["query"]), "state": item.get("state")})
    return out

def analyze_text(text):
    t = (text or "").lower()
    i = [x for x in IDENTITY if x in t]
    o = [x for x in OUTRAGE if x in t]
    a = [x for x in ACTORS if x in t]
    c = [x for x in CRIME if x in t]
    s = [x for x in SCANDAL if x in t]
    score = round(len(i)*1.8 + len(o)*1.0 + len(a)*0.8 - len(c)*2.5 - len(s)*2.6, 1)
    maybe = ((i and o) or (i and a) or len(i) >= 2 or (score >= 2.8 and i)) and len(c) < 2 and not (s and not i)
    return {"maybe_relevant": maybe, "lexical_score": score}

def article_key(item):
    return normalize_url(item.get("url")) or re.sub(r"\W+", "-", item.get("title","").lower()).strip("-")

def fetch_candidates(spec):
    parsed = feedparser.parse(spec["url"])
    entries = getattr(parsed, "entries", [])[:MAX_CANDIDATES_PER_FEED]
    out = []
    for entry in entries:
        title = strip_html(getattr(entry, "title", ""))
        summary = strip_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        url = normalize_url(getattr(entry, "link", ""))
        if not title or not url:
            continue
        analysis = analyze_text(title + "\n" + summary)
        if not analysis["maybe_relevant"]:
            continue
        out.append({"title": title, "url": url, "summary": summary[:1000], "published": parse_date(entry), "source": spec["label"], "state": spec.get("state"), "prefilter": analysis})
    return out

def render_cards(items):
    if not items:
        return '<article class="story-card empty"><h3>Nothing in this section this run</h3></article>'
    cards = []
    for item in items:
        tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in item.get("tags", []))
        cards.append(f'<article class="story-card"><div class="story-meta"><span class="angle">{html.escape(item.get("angle","identity-outrage story"))}</span><span>{html.escape(item.get("state") or "US")}</span><span>score {float(item.get("score",0)):.1f}</span></div><h3><a href="{html.escape(item.get("url",""))}" target="_blank" rel="noopener noreferrer">{html.escape(item.get("title",""))}</a></h3><p class="summary">{html.escape(item.get("summary",""))}</p><div class="reason">{html.escape(item.get("reason",""))}</div><div class="tags">{tags}</div><div class="source">{html.escape(item.get("source",""))}</div></article>')
    return "".join(cards)

def render_html(payload, before_dedupe, after_dedupe):
    counts = payload["counts"]
    note = "archive ignored for this run" if IGNORE_SEEN else "archive dedupe enabled"
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>National Association of Worried White People</title>
<meta name="description" content="A satire-flavored tracker for white grievance rhetoric, anti-DEI backlash, anti-Muslim targeting, anti-trans panic, book bans, and symbolic U.S. identity outrage.">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<style>
:root{{--bg:#07111e;--panel:#101c2d;--panel2:#13233a;--text:#eef4ff;--muted:#a9b7cd;--line:#29476f;--tag:#183251;--accent:#9cd0ff;--accent2:#8bc4ff;}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at top,#0b1930,#06101b 55%);color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif}}
.wrap{{max-width:1460px;margin:0 auto;padding:30px 24px 84px}} .brand{{display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
.logo{{width:58px;height:58px;border-radius:16px;background:linear-gradient(180deg,#163256,#0e2139);border:1px solid var(--line);display:grid;place-items:center;font-weight:800;font-size:24px;color:var(--accent)}}
.kicker{{text-transform:uppercase;letter-spacing:.14em;color:var(--accent);font-size:12px;font-weight:700}} h1{{font-size:64px;line-height:1.0;margin:6px 0 12px;letter-spacing:-.03em}}
.sub{{max-width:1030px;color:var(--muted);font-size:20px;margin:0 0 24px}} .stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:34px}} .pill{{border:1px solid var(--line);background:rgba(19,35,58,.9);padding:10px 15px;border-radius:999px}}
.section{{margin-top:40px}} .section h2{{font-size:38px;margin:0}} .section p{{margin:4px 0 0;color:var(--muted)}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:22px}}
.story-card{{background:linear-gradient(180deg,rgba(16,28,45,.96),rgba(10,21,35,.96));border:1px solid var(--line);border-radius:26px;padding:22px;box-shadow:0 18px 34px rgba(0,0,0,.22)}} .story-card.empty{{display:flex;align-items:center;justify-content:center;min-height:120px}}
.story-card h3{{margin:10px 0 12px;font-size:26px;line-height:1.14}} .story-card h3 a{{color:var(--text);text-decoration:none}} .story-card h3 a:hover{{text-decoration:underline}}
.story-meta{{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:14px}} .story-meta .angle{{color:var(--accent2);font-weight:700}} .summary{{font-size:17px;margin:0 0 12px}} .reason{{color:var(--accent);font-weight:700;margin:10px 0 0}}
.tags{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}} .tag{{border:1px solid var(--line);background:var(--tag);border-radius:999px;padding:6px 11px;font-size:14px}} .source{{margin-top:14px;color:var(--muted);font-size:14px}} .footer{{margin-top:46px;color:var(--muted);font-size:14px}}
@media (max-width:900px){{h1{{font-size:48px}}.sub{{font-size:18px}}}}
</style></head><body>
<div class="wrap">
<div class="brand"><div class="logo">NW</div><div><div class="kicker">Satire tracker</div><h1>National Association of Worried White People</h1></div></div>
<p class="sub">A satire-flavored tracker for U.S. culture-war stories centered on white grievance rhetoric, anti-DEI backlash, anti-Muslim school targeting, anti-trans panic, book bans, “parents’ rights” campaigns, and other symbolic identity outrage.</p>
<div class="stats">
<div class="pill">kept: {counts["kept"]}</div><div class="pill">in the wings: {counts["wings"]}</div><div class="pill">reviewed: {counts["reviewed"]}</div><div class="pill">rejected: {counts["rejected"]}</div><div class="pill">before dedupe: {before_dedupe}</div><div class="pill">after dedupe: {after_dedupe}</div><div class="pill">{note}</div><div class="pill">generated: {html.escape(now)}</div>
</div>
<section class="section"><h2>Kept</h2><p>Stories clearly on-theme for the site.</p><div class="grid">{render_cards(payload["kept"])}</div></section>
<section class="section"><h2>In the wings</h2><p>Borderline, adjacent, or weak-signal stories worth a second look.</p><div class="grid">{render_cards(payload["in_the_wings"])}</div></section>
<div class="footer">Generated automatically from RSS and Google News RSS sources. Stories are filtered for identity-focused backlash and downgraded or rejected when they look like generic scandal, crime, or unrelated politics.</div>
</div></body></html>'''

def write_favicon():
    FAVICON_FILE.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0f2139"/><rect x="3" y="3" width="58" height="58" rx="12" fill="none" stroke="#2b466f"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="26" font-weight="700" fill="#9cd0ff">NW</text></svg>', encoding="utf-8")

def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    specs = load_feed_specs()
    archive = load_json(ARCHIVE_FILE, {"seen": [], "reviews": []})
    seen = set(archive.get("seen", [])) if isinstance(archive, dict) else set()
    reviews = archive.get("reviews", []) if isinstance(archive, dict) else []
    if IGNORE_SEEN:
        seen = set()
    raw = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = {ex.submit(fetch_candidates, spec): spec for spec in specs}
        for fut in as_completed(futures):
            spec = futures[fut]
            try:
                items = fut.result()
                raw.extend(items)
                print(f'{spec["label"]}: {len(items)} candidates')
            except Exception as e:
                print(f'{spec["label"]}: ERROR {e}')
    raw.sort(key=lambda x: (x["prefilter"]["lexical_score"], x.get("published","")), reverse=True)
    before_dedupe = len(raw)
    candidates, seen_local = [], set()
    for item in raw:
        key = article_key(item)
        title_key = re.sub(r"\W+", " ", item.get("title","").lower()).strip()
        if not IGNORE_SEEN and (key in seen or title_key in seen):
            continue
        if key in seen_local or title_key in seen_local:
            continue
        seen_local.add(key); seen_local.add(title_key); candidates.append(item)
    after_dedupe = len(candidates)
    candidates = candidates[:MAX_AI_REVIEWS_PER_RUN]
    reviewed, kept, wings, rejected = [], [], [], []
    with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
        futures = {ex.submit(evaluate_article, item): item for item in candidates}
        for fut in as_completed(futures):
            item = futures[fut]
            row = {**item, **fut.result()}
            reviewed.append(row)
            score = float(row.get("score", 0)); bucket = row.get("bucket", "reject")
            if bucket == "keep" and score >= KEEP_MIN_SCORE:
                kept.append(row)
            elif bucket in {"keep","wings"} and score >= WINGS_MIN_SCORE:
                if bucket == "keep":
                    row["bucket"] = "wings"
                wings.append(row)
            else:
                rejected.append(row)
    for item in reviewed:
        seen.add(article_key(item))
        seen.add(re.sub(r"\W+", " ", item.get("title","").lower()).strip())
    reviews.extend([{"title": r.get("title"), "url": r.get("url"), "source": r.get("source"), "bucket": r.get("bucket"), "score": r.get("score"), "published": r.get("published")} for r in reviewed])
    payload = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "counts": {"kept": len(kept), "wings": len(wings), "rejected": len(rejected), "reviewed": len(reviewed)}, "kept": sorted(kept, key=lambda x: x.get("score",0), reverse=True), "in_the_wings": sorted(wings, key=lambda x: x.get("score",0), reverse=True), "rejected": sorted(rejected, key=lambda x: x.get("score",0), reverse=True)[:200]}
    save_json(ARCHIVE_FILE, {"seen": sorted(seen), "reviews": reviews[-5000:]})
    save_json(OUTPUT_FILE, payload)
    INDEX_FILE.write_text(render_html(payload, before_dedupe, after_dedupe), encoding="utf-8")
    write_favicon()
    print(f"Saved {INDEX_FILE}")
    print(f"Saved {OUTPUT_FILE}")
    print(f"Saved {FAVICON_FILE}")

if __name__ == "__main__":
    main()

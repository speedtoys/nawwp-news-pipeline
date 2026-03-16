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

MAX_CANDIDATES_PER_FEED = int(os.getenv("MAX_CANDIDATES_PER_FEED", "25"))
MAX_AI_REVIEWS_PER_RUN = int(os.getenv("MAX_AI_REVIEWS_PER_RUN", "120"))
KEEP_MIN_SCORE = float(os.getenv("KEEP_MIN_SCORE", "4.0"))
WINGS_MIN_SCORE = float(os.getenv("WINGS_MIN_SCORE", "2.5"))
FETCH_WORKERS = int(os.getenv("FETCH_WORKERS", "8"))
AI_WORKERS = int(os.getenv("AI_WORKERS", "4"))
IGNORE_SEEN = os.getenv("IGNORE_SEEN", "0").lower() in {"1","true","yes","y"}

IDENTITY = [
    "dei","diversity","equity","inclusion","anti-woke","woke","trans","transgender",
    "pronoun","drag","pride","lgbt","lgbtq","book ban","banned books","library",
    "school board","parents' rights","voucher","school choice","religious liberty",
    "christian values","traditional values","western civilization","white people",
    "white boys","young white men","muslim","islamic","muslim school","islamic school",
    "immigrant","immigration","dei office","cair"
]
OUTRAGE = [
    "backlash","outrage","criticized","criticizes","slams","targets","opposes","ban","bans",
    "blocks","defund","exclude","excluded","remove","pull funding","lawsuit","sues","debate"
]
ACTORS = [
    "maga","trump","republican","republicans","gop","conservative","conservatives",
    "fox news","moms for liberty","charlie kirk","erika kirk","governor","attorney general"
]
CRIME = [
    "shooting","murder","bombing","terror","arrested","charged with","indicted","convicted",
    "sentenced","assault","rape","sexual assault","trafficking","abuse","homicide","stabbing"
]
SCANDAL = [
    "fake electors","alternate electors","electors","election fraud","campaign finance",
    "bribery","corruption","indictment","prosecution","felony","embezzlement"
]

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
            out.append({"label": item["label"], "url": item["url"], "state": item.get("state"), "bucket": item.get("bucket","rss")})
    for item in cfg.get("google_news_queries", []):
        if item.get("enabled", True):
            out.append({"label": item["label"], "url": build_google_news_rss(item["query"]), "state": item.get("state"), "bucket": item.get("bucket","google-news")})
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
    return {
        "maybe_relevant": maybe,
        "lexical_score": score,
        "include_hits": i[:8],
        "outrage_hits": o[:6],
        "actor_hits": a[:6],
        "crime_hits": c[:6],
        "scandal_hits": s[:6],
    }

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
        out.append({
            "title": title,
            "url": url,
            "summary": summary[:1000],
            "published": parse_date(entry),
            "source": spec["label"],
            "state": spec.get("state"),
            "prefilter": analysis,
        })
    return out

def render_cards(items):
    if not items:
        return '<article class="card"><h3>Nothing in this section this run</h3></article>'
    html_parts = []
    for item in items:
        tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in item.get("tags", []))
        html_parts.append(
            f'<article class="card"><div class="meta"><span>{html.escape(item.get("angle","candidate"))}</span><span>{html.escape(item.get("state") or "US")}</span><span>score {float(item.get("score",0)):.1f}</span></div><h3><a href="{html.escape(item.get("url",""))}" target="_blank" rel="noopener noreferrer">{html.escape(item.get("title",""))}</a></h3><p>{html.escape(item.get("summary",""))}</p><div class="reason">{html.escape(item.get("reason",""))}</div><div class="tags">{tags}</div><div class="source">{html.escape(item.get("source",""))}</div></article>'
        )
    return "".join(html_parts)

def render_html(payload, before_dedupe, after_dedupe):
    counts = payload["counts"]
    note = "archive ignored for this run" if IGNORE_SEEN else "archive dedupe enabled"
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>National Association of Worried White People</title>
<style>
:root{{--bg:#08111d;--panel:#101a2b;--panel2:#152235;--text:#eff4ff;--muted:#a8b5ca;--line:#2b466f;--tag:#17304f;--accent:#9fd0ff;}}
body{{margin:0;background:#08111d;color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;}}
.wrap{{max-width:1400px;margin:0 auto;padding:32px 24px 80px;}}
h1{{font-size:58px;line-height:1.02;margin:0 0 12px;}}
.sub{{color:var(--muted);font-size:18px;margin-bottom:24px;max-width:980px;}}
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:30px;}}
.pill{{border:1px solid var(--line);background:var(--panel2);padding:10px 15px;border-radius:999px;}}
.section{{margin-top:42px;}}
.section h2{{font-size:34px;margin:0 0 10px;}}
.small{{color:var(--muted);font-size:14px;margin:0 0 18px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:22px;}}
.card{{background:#101a2b;border:1px solid var(--line);border-radius:24px;padding:22px;}}
.card h3{{margin:10px 0 12px;font-size:28px;line-height:1.16;}}
.card h3 a{{color:var(--text);text-decoration:none;}}
.meta{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:14px;}}
.reason{{margin-top:14px;color:var(--accent);font-weight:600;}}
.tags{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;}}
.tag{{border:1px solid var(--line);background:var(--tag);border-radius:999px;padding:6px 11px;font-size:14px;}}
.source{{margin-top:16px;color:var(--muted);font-size:14px;}}
</style>
</head>
<body>
<div class="wrap">
<h1>National Association of Worried White People</h1>
<div class="sub">A satire-flavored tracker for U.S. culture-war stories centered on white grievance rhetoric, anti-DEI backlash, anti-Muslim school targeting, anti-trans panic, book bans, “parents’ rights” campaigns, and other symbolic identity outrage.</div>
<div class="stats">
<div class="pill">kept: {counts["kept"]}</div>
<div class="pill">in the wings: {counts["wings"]}</div>
<div class="pill">reviewed: {counts["reviewed"]}</div>
<div class="pill">rejected: {counts["rejected"]}</div>
<div class="pill">before dedupe: {before_dedupe}</div>
<div class="pill">after dedupe: {after_dedupe}</div>
<div class="pill">{note}</div>
<div class="pill">generated: {html.escape(now)}</div>
</div>
<section class="section"><h2>Kept</h2><div class="grid">{render_cards(payload["kept"])}</div></section>
<section class="section"><h2>In the wings</h2><div class="small">Borderline or adjacent stories worth a second look.</div><div class="grid">{render_cards(payload["in_the_wings"])}</div></section>
</div>
</body></html>'''

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

    candidates = []
    seen_local = set()
    for item in raw:
        key = article_key(item)
        title_key = re.sub(r"\W+", " ", item.get("title","").lower()).strip()
        if not IGNORE_SEEN and (key in seen or title_key in seen):
            continue
        if key in seen_local or title_key in seen_local:
            continue
        seen_local.add(key)
        seen_local.add(title_key)
        candidates.append(item)

    after_dedupe = len(candidates)
    candidates = candidates[:MAX_AI_REVIEWS_PER_RUN]

    reviewed, kept, wings, rejected = [], [], [], []
    with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
        futures = {ex.submit(evaluate_article, item): item for item in candidates}
        for fut in as_completed(futures):
            item = futures[fut]
            review = fut.result()
            row = {**item, **review}
            reviewed.append(row)
            score = float(row.get("score", 0))
            bucket = row.get("bucket", "reject")
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

    reviews.extend([{
        "title": r.get("title"),
        "url": r.get("url"),
        "source": r.get("source"),
        "bucket": r.get("bucket"),
        "score": r.get("score"),
        "published": r.get("published"),
    } for r in reviewed])

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "counts": {
            "kept": len(kept),
            "wings": len(wings),
            "rejected": len(rejected),
            "reviewed": len(reviewed),
        },
        "kept": sorted(kept, key=lambda x: x.get("score",0), reverse=True),
        "in_the_wings": sorted(wings, key=lambda x: x.get("score",0), reverse=True),
        "rejected": sorted(rejected, key=lambda x: x.get("score",0), reverse=True)[:200],
    }

    save_json(ARCHIVE_FILE, {"seen": sorted(seen), "reviews": reviews[-5000:]})
    save_json(OUTPUT_FILE, payload)
    INDEX_FILE.write_text(render_html(payload, before_dedupe, after_dedupe), encoding="utf-8")
    print(f"Saved {INDEX_FILE}")
    print(f"Saved {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

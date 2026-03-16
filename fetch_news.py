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

def format_date(iso_str):
    try:
        d = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return d.strftime("%b %d, %Y")
    except Exception:
        return ""

def story_card(item, compact=False):
    tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in item.get("tags", [])[:4])
    state = html.escape(item.get("state") or "US")
    title = html.escape(item.get("title",""))
    url = html.escape(item.get("url",""))
    summary = html.escape(item.get("summary",""))
    angle = html.escape(item.get("angle","identity-outrage story"))
    source = html.escape(item.get("source",""))
    published = format_date(item.get("published",""))
    score = float(item.get("score", 0))
    cls = "story-card compact" if compact else "story-card"
    meta = f'<div class="story-meta"><span class="angle">{angle}</span><span>{state}</span><span>{published}</span><span>score {score:.1f}</span></div>'
    if compact:
        return f'<article class="{cls}">{meta}<h3><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h3><div class="source">{source}</div></article>'
    return f'<article class="{cls}">{meta}<h3><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h3><p class="summary">{summary}</p><div class="tags">{tags}</div><div class="source">{source}</div></article>'

def render_lead(kept):
    if not kept:
        return '<section class="lead-grid"><article class="lead-card"><h2>No lead story yet</h2><p>Run the pipeline to generate the next edition.</p></article></section>'
    lead = kept[0]
    secondary = kept[1:5]
    lead_tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in lead.get("tags", [])[:5])
    lead_html = f'''<article class="lead-card"><div class="eyebrow">Top story</div><div class="story-meta"><span class="angle">{html.escape(lead.get("angle","identity-outrage story"))}</span><span>{html.escape(lead.get("state") or "US")}</span><span>{format_date(lead.get("published",""))}</span><span>score {float(lead.get("score",0)):.1f}</span></div><h2><a href="{html.escape(lead.get("url",""))}" target="_blank" rel="noopener noreferrer">{html.escape(lead.get("title",""))}</a></h2><p>{html.escape(lead.get("summary",""))}</p><div class="tags">{lead_tags}</div><div class="source">{html.escape(lead.get("source",""))}</div></article>'''
    right = ''.join(story_card(x, compact=True) for x in secondary) or '<article class="story-card compact"><h3>No secondary stories yet</h3></article>'
    return f'<section class="lead-grid">{lead_html}<div class="lead-side">{right}</div></section>'

def render_section(title, subtitle, items, compact=False):
    body = ''.join(story_card(x, compact=compact) for x in items) if items else '<article class="story-card empty"><h3>Nothing in this section this run</h3></article>'
    grid_class = "grid compact-grid" if compact else "grid"
    return f'<section class="section"><div class="section-head"><h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p></div><div class="{grid_class}">{body}</div></section>'

def render_sidebar(payload, before_dedupe, after_dedupe):
    counts = payload["counts"]
    note = "archive ignored for this run" if IGNORE_SEEN else "archive dedupe enabled"
    return f'''<aside class="sidebar"><div class="sidebar-card"><div class="sidebar-title">Edition metrics</div><div class="metric"><span>Kept</span><strong>{counts["kept"]}</strong></div><div class="metric"><span>In the wings</span><strong>{counts["wings"]}</strong></div><div class="metric"><span>Rejected</span><strong>{counts["rejected"]}</strong></div><div class="metric"><span>Reviewed</span><strong>{counts["reviewed"]}</strong></div><div class="metric"><span>Before dedupe</span><strong>{before_dedupe}</strong></div><div class="metric"><span>After dedupe</span><strong>{after_dedupe}</strong></div></div><div class="sidebar-card"><div class="sidebar-title">About this feed</div><p>A satire-flavored tracker for white grievance rhetoric, anti-DEI backlash, anti-Muslim school targeting, anti-trans panic, book bans, “parents’ rights” campaigns, and other symbolic identity outrage.</p><p class="muted">{html.escape(note)}</p></div></aside>'''

def render_html(payload, before_dedupe, after_dedupe):
    kept = payload["kept"]
    wings = payload["in_the_wings"]
    now = dt.datetime.now().strftime("%B %d, %Y %I:%M %p")
    lead = render_lead(kept)
    features = kept[5:17]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>National Association of Worried White People</title><meta name="description" content="A satire-flavored tracker for white grievance rhetoric, anti-DEI backlash, anti-Muslim targeting, anti-trans panic, book bans, and symbolic U.S. identity outrage."><link rel="icon" type="image/svg+xml" href="favicon.svg"><style>:root{{--bg:#f5f1e8;--paper:#fffdf9;--ink:#131313;--muted:#666;--line:#ddd3c4;--accent:#931b1d;--accent2:#1b457d;--tag:#f3e7d5}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Georgia,"Times New Roman",serif}}.wrap{{max-width:1420px;margin:0 auto;padding:0 22px 70px}}.topbar{{border-bottom:1px solid var(--line);padding:14px 0 10px;color:var(--muted);font:13px/1.4 Arial,Helvetica,sans-serif;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}.masthead{{padding:20px 0 18px;border-bottom:4px double var(--line)}}.kicker{{font:700 11px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.18em;text-transform:uppercase;color:var(--accent2)}}h1{{margin:8px 0 8px;font-size:64px;line-height:1.0;letter-spacing:-.03em}}.deck{{max-width:980px;color:#3d3d3d;font-size:21px;line-height:1.45}}.layout{{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:28px;margin-top:28px}}.lead-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);gap:24px}}.lead-card,.story-card,.sidebar-card{{background:var(--paper);border:1px solid var(--line);box-shadow:0 2px 14px rgba(0,0,0,.04)}}.lead-card{{padding:24px 26px}}.lead-card h2{{font-size:44px;line-height:1.03;margin:10px 0 12px}}.lead-card p{{font-size:20px;line-height:1.5;color:#2d2d2d}}.lead-side{{display:grid;gap:16px}}.story-card{{padding:18px 20px}}.story-card.compact h3{{font-size:24px}}.story-card h3{{margin:8px 0 10px;font-size:28px;line-height:1.12}}.story-card a,.lead-card a{{color:inherit;text-decoration:none}}.story-card a:hover,.lead-card a:hover{{text-decoration:underline}}.story-meta{{display:flex;gap:10px;flex-wrap:wrap;font:13px/1.4 Arial,Helvetica,sans-serif;color:var(--muted)}}.story-meta .angle{{color:var(--accent);font-weight:700}}.eyebrow{{font:700 11px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}}.summary{{margin:0 0 12px;color:#2c2c2c}}.tags{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.tag{{background:var(--tag);border:1px solid #e4d3b8;border-radius:999px;padding:5px 9px;font:12px/1.2 Arial,Helvetica,sans-serif;color:#6a4b20}}.source{{margin-top:12px;font:13px/1.4 Arial,Helvetica,sans-serif;color:var(--muted)}}.section{{margin-top:34px}}.section-head{{display:flex;justify-content:space-between;gap:16px;align-items:end;border-top:3px solid var(--ink);padding-top:12px;margin-bottom:14px}}.section h2{{margin:0;font-size:34px}}.section p{{margin:0;color:var(--muted);font:15px/1.4 Arial,Helvetica,sans-serif}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}}.compact-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.sidebar{{display:grid;gap:18px}}.sidebar-card{{padding:18px 18px 14px}}.sidebar-title{{font:700 13px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--accent2);margin-bottom:14px}}.metric{{display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-top:1px solid var(--line);font:14px/1.4 Arial,Helvetica,sans-serif}}.metric:first-of-type{{border-top:0;padding-top:0}}.metric strong{{font-size:20px;color:var(--ink)}}.muted{{color:var(--muted);font:14px/1.5 Arial,Helvetica,sans-serif}}.footer{{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);font:14px/1.5 Arial,Helvetica,sans-serif;color:var(--muted)}}@media (max-width:1180px){{.layout{{grid-template-columns:1fr}}.sidebar{{order:-1}}}}@media (max-width:980px){{.lead-grid{{grid-template-columns:1fr}}.grid,.compact-grid{{grid-template-columns:1fr}}h1{{font-size:46px}}.lead-card h2{{font-size:34px}}.deck{{font-size:18px}}}}</style></head><body><div class="wrap"><div class="topbar"><div>National Association of Worried White People</div><div>Latest edition · {html.escape(now)}</div></div><header class="masthead"><div class="kicker">Independent panic desk</div><h1>National Association of Worried White People</h1><div class="deck">A satire-flavored tracker for U.S. culture-war stories centered on white grievance rhetoric, anti-DEI backlash, anti-Muslim school targeting, anti-trans panic, book bans, “parents’ rights” campaigns, and other symbolic identity outrage.</div></header><div class="layout"><main>{lead}{render_section("Features", "Clear on-theme stories from this edition.", features)}{render_section("In the wings", "Borderline or adjacent stories worth a second look.", wings[:12], compact=True)}</main>{render_sidebar(payload, before_dedupe, after_dedupe)}</div><div class="footer">Generated automatically from RSS and Google News RSS sources. Stories are filtered for identity-focused backlash and downgraded or rejected when they look like generic scandal, crime, or unrelated politics.</div></div></body></html>'''

def write_favicon():
    FAVICON_FILE.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="8" fill="#931b1d"/><rect x="3" y="3" width="58" height="58" rx="6" fill="none" stroke="#f3d9a6"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" font-family="Georgia, serif" font-size="24" font-weight="700" fill="#fff8eb">NW</text></svg>', encoding="utf-8")

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

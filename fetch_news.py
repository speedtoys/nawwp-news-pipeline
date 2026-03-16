#!/usr/bin/env python3
import datetime as dt
import html
import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime

import feedparser

from score_articles import evaluate_article

CONFIG_FILE = "rss_sources.json"
ARCHIVE_FILE = "archive.json"
OUTPUT_FILE = "news.json"
HTML_FILE = "latest.html"

MAX_CANDIDATES_PER_FEED = int(os.getenv("MAX_CANDIDATES_PER_FEED", "25"))
MAX_AI_REVIEWS_PER_RUN = int(os.getenv("MAX_AI_REVIEWS_PER_RUN", "160"))
KEEP_MIN_SCORE = float(os.getenv("KEEP_MIN_SCORE", "4.0"))
WINGS_MIN_SCORE = float(os.getenv("WINGS_MIN_SCORE", "2.6"))
FETCH_WORKERS = int(os.getenv("FETCH_WORKERS", "10"))
AI_WORKERS = int(os.getenv("AI_WORKERS", "4"))
IGNORE_SEEN = os.getenv("IGNORE_SEEN", "0").lower() in {"1", "true", "yes", "y"}

IDENTITY_TERMS = [
    "dei", "diversity", "equity", "inclusion", "affirmative action",
    "critical race theory", "crt", "anti-woke", "woke", "anti woke",
    "transgender", "trans", "gender ideology", "gender identity", "pronoun",
    "drag", "drag queen", "pride", "lgbt", "lgbtq", "nonbinary", "bathroom bill",
    "girls sports", "women's sports", "book ban", "banned books", "library",
    "curriculum", "school board", "parents' rights", "school choice", "voucher",
    "religious liberty", "christian values", "traditional values", "western civilization",
    "white grievance", "white people", "white boys", "young white men", "young white male",
    "white male man", "disenfranchise", "replacement", "heritage",
    "immigrant", "immigration", "illegal alien", "illegal aliens", "refugee",
    "muslim", "islam", "islamic", "mosque", "islamophobia", "sharia", "sharia law",
    "muslim school", "islamic school", "faith-based", "faith based",
    "diversity office", "dei office", "inclusive", "multicultural", "antisemitism",
    "jewish", "christian nationalist", "race-conscious", "race conscious",
    "merit", "meritocracy", "patriotic education", "american values", "cair",
]

OUTRAGE_TERMS = [
    "backlash", "outrage", "criticized", "criticises", "criticizes", "slam", "slams",
    "attacks", "targets", "opposes", "opposition", "bans", "ban", "blocks", "block",
    "defund", "defunds", "eliminate", "eliminates", "removes", "remove",
    "pull funding", "pulls funding", "exclude", "excluded", "excludes",
    "protests", "complains", "complaint", "boycott", "boycotts", "lawsuit", "sues",
    "hearing", "debate", "condemns", "denounces", "fights", "fighting",
    "pressure campaign", "parents rights", "parents' rights", "anti-woke", "anti woke",
]

RIGHT_ACTOR_TERMS = [
    "maga", "trump", "republican", "republicans", "gop", "conservative",
    "conservatives", "right-wing", "right wing", "fox news", "moms for liberty",
    "heritage foundation", "family policy", "alliance defending freedom",
    "liberty counsel", "turning point usa", "turning point", "charlie kirk", "erika kirk",
    "christian nationalist", "evangelical", "state lawmakers", "attorney general",
    "governor", "school board",
]

CRIME_VIOLENCE_TERMS = [
    "shooting", "shot", "killed", "murder", "murdered", "bomb", "bombing",
    "terror", "terrorism", "massacre", "arrested", "arrest", "charged with",
    "indicted", "convicted", "sentenced", "police", "sheriff", "assault", "rape",
    "sexual assault", "molest", "molestation", "trafficking", "abuse", "child porn",
    "pornography", "dead", "death", "homicide", "violent", "violence",
    "hate crime", "stabbing", "stabbed",
]

GENERIC_SCANDAL_TERMS = [
    "alternate electors", "fake electors", "electors", "election fraud",
    "voter fraud", "campaign finance", "bribery", "bribe", "corruption",
    "indictment", "indicted", "prosecution", "prosecutor", "convicted",
    "felony", "felonies", "forgery", "embezzlement", "money laundering",
]

FALSE_POSITIVE_CONTEXT = [
    "weather", "sports recap", "earnings", "stock price", "concert review",
    "movie review", "real estate", "recipe", "crossword", "horoscope",
]

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def strip_html(text):
    text = text or ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def normalize_url(url):
    if not url:
        return ""
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url

def build_google_news_rss(query):
    quoted = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={quoted}+when:30d&hl=en-US&gl=US&ceid=US:en"

def parse_date(entry):
    for raw in [getattr(entry, "published", None), getattr(entry, "updated", None), getattr(entry, "created", None)]:
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw).astimezone(dt.timezone.utc).isoformat()
        except Exception:
            continue
    return dt.datetime.now(dt.timezone.utc).isoformat()

def load_feed_specs():
    cfg = load_json(CONFIG_FILE, {})
    specs = []

    for item in cfg.get("rss_feeds", []):
        if item.get("enabled", True) and item.get("url"):
            specs.append({
                "label": item.get("label") or item.get("name") or item["url"],
                "kind": "rss",
                "url": item["url"],
                "state": item.get("state"),
                "bucket": item.get("bucket", "custom"),
            })

    for item in cfg.get("google_news_queries", []):
        if item.get("enabled", True) and item.get("query"):
            specs.append({
                "label": item.get("label") or item["query"],
                "kind": "google_news",
                "url": build_google_news_rss(item["query"]),
                "state": item.get("state"),
                "bucket": item.get("bucket", "google-news"),
            })
    return specs

def analyze_text(text):
    t = (text or "").lower()
    include_hits = [term for term in IDENTITY_TERMS if term in t]
    outrage_hits = [term for term in OUTRAGE_TERMS if term in t]
    actor_hits = [term for term in RIGHT_ACTOR_TERMS if term in t]
    crime_hits = [term for term in CRIME_VIOLENCE_TERMS if term in t]
    scandal_hits = [term for term in GENERIC_SCANDAL_TERMS if term in t]
    noise_hits = [term for term in FALSE_POSITIVE_CONTEXT if term in t]

    score = 0.0
    score += min(len(include_hits), 5) * 1.8
    score += min(len(outrage_hits), 4) * 1.0
    score += min(len(actor_hits), 3) * 0.9
    score -= min(len(crime_hits), 4) * 2.5
    score -= min(len(scandal_hits), 3) * 2.6
    score -= min(len(noise_hits), 2) * 1.5

    has_identity = len(include_hits) >= 1
    scandal_first = len(scandal_hits) >= 1 and not has_identity
    crime_first = len(crime_hits) >= 2

    maybe_relevant = (
        (has_identity and len(outrage_hits) >= 1 and len(crime_hits) == 0)
        or (has_identity and len(actor_hits) >= 1 and len(crime_hits) <= 1)
        or (len(include_hits) >= 2 and len(crime_hits) == 0)
        or (score >= 2.8 and has_identity)
        or (len(actor_hits) >= 1 and len(outrage_hits) >= 1 and has_identity)
    )

    return {
        "maybe_relevant": maybe_relevant and not crime_first and not scandal_first,
        "lexical_score": round(score, 2),
        "include_hits": include_hits[:10],
        "outrage_hits": outrage_hits[:8],
        "actor_hits": actor_hits[:8],
        "crime_hits": crime_hits[:8],
        "scandal_hits": scandal_hits[:8],
        "noise_hits": noise_hits[:4],
    }

def article_key(article):
    return normalize_url(article.get("url")) or re.sub(r"\W+", "-", article.get("title", "").lower()).strip("-")

def fetch_candidates(feed_spec):
    parsed = feedparser.parse(feed_spec["url"])
    entries = getattr(parsed, "entries", [])[:MAX_CANDIDATES_PER_FEED]
    items = []

    for entry in entries:
        title = strip_html(getattr(entry, "title", ""))
        summary = strip_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        url = normalize_url(getattr(entry, "link", ""))
        if not title or not url:
            continue

        full_text = f"{title}\n{summary}"
        analysis = analyze_text(full_text)
        if not analysis["maybe_relevant"]:
            continue

        items.append({
            "title": title,
            "url": url,
            "summary": summary[:1200],
            "published": parse_date(entry),
            "source": feed_spec["label"],
            "bucket_source": feed_spec["bucket"],
            "state": feed_spec.get("state"),
            "prefilter": analysis,
        })
    return items

def dedupe_candidates(candidates, seen):
    if IGNORE_SEEN:
        return list(candidates)

    deduped = []
    seen_local = set()

    for item in candidates:
        key = article_key(item)
        title_key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
        if key in seen or key in seen_local or title_key in seen or title_key in seen_local:
            continue
        seen_local.add(key)
        seen_local.add(title_key)
        deduped.append(item)
    return deduped

def sort_candidates(candidates):
    return sorted(
        candidates,
        key=lambda x: (x["prefilter"]["lexical_score"], x.get("published", "")),
        reverse=True,
    )

def review_candidates(candidates):
    reviewed = []
    kept = []
    wings = []
    rejected = []

    to_review = candidates[:MAX_AI_REVIEWS_PER_RUN]

    with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
        future_map = {ex.submit(evaluate_article, article): article for article in to_review}
        done = 0
        for fut in as_completed(future_map):
            article = future_map[fut]
            done += 1
            try:
                review = fut.result()
            except Exception as e:
                review = {
                    "bucket": "reject",
                    "score": 0.0,
                    "tags": ["scoring-error"],
                    "angle": "scoring failed",
                    "summary": article.get("summary", "")[:600],
                    "reason": f"evaluate_article exception: {type(e).__name__}: {e}",
                }

            row = {**article, **review}
            reviewed.append(row)

            bucket = row.get("bucket", "reject")
            score = float(row.get("score", 0))
            print(f"[AI {done}/{len(to_review)}] {bucket.upper()} {score:.1f} :: {article['title'][:100]}")

            if bucket == "keep" and score >= KEEP_MIN_SCORE:
                kept.append(row)
            elif bucket in {"keep", "wings"} and score >= WINGS_MIN_SCORE:
                if bucket == "keep":
                    row = {**row, "bucket": "wings", "reason": f"Demoted to wings due to score below KEEP_MIN_SCORE. {row.get('reason','')}"}
                wings.append(row)
            else:
                rejected.append(row)

    kept = sorted(kept, key=lambda x: (float(x.get("score", 0)), x.get("published", "")), reverse=True)
    wings = sorted(wings, key=lambda x: (float(x.get("score", 0)), x.get("published", "")), reverse=True)
    rejected = sorted(rejected, key=lambda x: (float(x.get("score", 0)), x.get("published", "")), reverse=True)
    return reviewed, kept, wings, rejected

def render_cards(items):
    cards = []
    for item in items:
        tags = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in item.get("tags", []))
        cards.append(f"""
        <article class="card">
          <div class="meta">
            <span>{html.escape(item.get("angle", "candidate"))}</span>
            <span>{html.escape(item.get("state") or "US")}</span>
            <span>score {float(item.get("score", 0)):.1f}</span>
          </div>
          <h3><a href="{html.escape(item.get("url", ""))}" target="_blank" rel="noopener noreferrer">{html.escape(item.get("title", ""))}</a></h3>
          <p>{html.escape(item.get("summary", ""))}</p>
          <div class="reason">{html.escape(item.get("reason", ""))}</div>
          <div class="tags">{tags}</div>
          <div class="source">{html.escape(item.get("source", ""))}</div>
        </article>
        """)
    if not cards:
        cards.append('<article class="card"><h3>Nothing in this section this run</h3></article>')
    return "".join(cards)

def render_html(kept_items, wings_items, reviewed, rejected, before_dedupe, after_dedupe):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    seen_note = "archive ignored for this run" if IGNORE_SEEN else "archive dedupe enabled"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAWWP candidate stories</title>
<style>
:root {{
  --bg:#060b15; --panel:#0f1725; --panel2:#111c2d; --text:#e8eefc; --muted:#aeb9d0; --line:#284164; --tag:#152741;
}}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif; }}
.wrap {{ max-width:1460px; margin:0 auto; padding:34px 28px 80px; }}
h1 {{ font-size:58px; line-height:1.05; margin:0 0 10px; }}
.sub {{ color:var(--muted); font-size:18px; margin-bottom:24px; }}
.stats {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:30px; }}
.pill {{ border:1px solid var(--line); background:var(--panel2); padding:10px 16px; border-radius:999px; color:var(--text); }}
.section {{ margin-top:36px; }}
.section h2 {{ font-size:34px; margin:0 0 18px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:22px; }}
.card {{ background:linear-gradient(180deg,var(--panel),#0c1421); border:1px solid var(--line); border-radius:24px; padding:22px; box-shadow:0 12px 32px rgba(0,0,0,.26); }}
.card h3 {{ margin:10px 0 12px; font-size:28px; line-height:1.18; }}
.card h3 a {{ color:var(--text); text-decoration:none; }}
.card h3 a:hover {{ text-decoration:underline; }}
.meta {{ display:flex; gap:14px; flex-wrap:wrap; color:var(--muted); font-size:15px; }}
.reason {{ margin-top:14px; color:#97c7ff; font-weight:600; }}
.tags {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }}
.tag {{ border:1px solid var(--line); background:var(--tag); border-radius:999px; padding:7px 12px; color:var(--text); }}
.source {{ margin-top:16px; color:var(--muted); font-size:14px; }}
.small {{ color:var(--muted); font-size:14px; margin-top:8px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>NAWWP candidate stories</h1>
<div class="sub">Generated {html.escape(now)} • tuned for U.S. identity-outrage coverage with a separate “In the wings” lane for borderline stories.</div>
<div class="stats">
  <div class="pill">kept: {len(kept_items)}</div>
  <div class="pill">in the wings: {len(wings_items)}</div>
  <div class="pill">reviewed: {len(reviewed)}</div>
  <div class="pill">rejected: {len(rejected)}</div>
  <div class="pill">before dedupe: {before_dedupe}</div>
  <div class="pill">after dedupe: {after_dedupe}</div>
  <div class="pill">{seen_note}</div>
</div>

<section class="section">
  <h2>Kept</h2>
  <div class="grid">{render_cards(kept_items)}</div>
</section>

<section class="section">
  <h2>In the wings</h2>
  <div class="small">Borderline, adjacent, or weak-signal stories worth a second look.</div>
  <div class="grid">{render_cards(wings_items)}</div>
</section>
</div>
</body>
</html>
"""

def main():
    feed_specs = load_feed_specs()
    print(f"Loaded {len(feed_specs)} feeds/queries")

    archive = load_json(ARCHIVE_FILE, default={"seen": [], "reviews": []})
    if isinstance(archive, list):
        seen = set()
        reviews = archive
    elif isinstance(archive, dict):
        seen = set(archive.get("seen", []))
        reviews = archive.get("reviews", [])
    else:
        seen = set()
        reviews = []

    if IGNORE_SEEN:
        print("IGNORE_SEEN=1 -> archive dedupe disabled for this run")
        seen = set()

    raw_candidates = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        future_map = {ex.submit(fetch_candidates, spec): spec for spec in feed_specs}
        done = 0
        for fut in as_completed(future_map):
            spec = future_map[fut]
            done += 1
            try:
                items = fut.result()
                raw_candidates.extend(items)
                print(f"[{done}/{len(feed_specs)}] {spec['label']}: {len(items)} candidates")
            except Exception as e:
                print(f"[{done}/{len(feed_specs)}] {spec['label']}: ERROR {type(e).__name__}: {e}")

    before_dedupe = len(raw_candidates)
    candidates = dedupe_candidates(sort_candidates(raw_candidates), seen)
    after_dedupe = len(candidates)
    print(f"Candidates before dedupe: {before_dedupe}")
    print(f"Candidates after dedupe:  {after_dedupe}")
    print(f"Deduped candidates ready for review: {len(candidates)}")

    reviewed, kept, wings, rejected = review_candidates(candidates)

    for item in reviewed:
        key = article_key(item)
        title_key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
        seen.add(key)
        seen.add(title_key)

    reviews.extend([
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "source": r.get("source"),
            "state": r.get("state"),
            "score": r.get("score"),
            "bucket": r.get("bucket"),
            "angle": r.get("angle"),
            "reason": r.get("reason"),
            "tags": r.get("tags"),
            "published": r.get("published"),
        }
        for r in reviewed
    ])
    reviews = reviews[-5000:]

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "counts": {
            "kept": len(kept),
            "wings": len(wings),
            "rejected": len(rejected),
            "reviewed": len(reviewed),
            "before_dedupe": before_dedupe,
            "after_dedupe": after_dedupe,
        },
        "kept": kept,
        "in_the_wings": wings,
        "rejected": rejected[:250],
    }

    save_json(ARCHIVE_FILE, {"seen": sorted(seen), "reviews": reviews})
    save_json(OUTPUT_FILE, payload)
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(render_html(kept, wings, reviewed, rejected, before_dedupe, after_dedupe))

    print(f"Saved kept={len(kept)} wings={len(wings)} rejected={len(rejected)} to {OUTPUT_FILE}")
    print(f"Wrote {HTML_FILE}")

if __name__ == "__main__":
    main()

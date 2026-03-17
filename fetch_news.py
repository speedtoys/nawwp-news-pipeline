
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

MAX_CANDIDATES_PER_FEED = int(os.getenv("MAX_CANDIDATES_PER_FEED", "80"))
MAX_AI_REVIEWS_PER_RUN = int(os.getenv("MAX_AI_REVIEWS_PER_RUN", "260"))
KEEP_MIN_SCORE = float(os.getenv("KEEP_MIN_SCORE", "4.0"))
WINGS_MIN_SCORE = float(os.getenv("WINGS_MIN_SCORE", "2.5"))
FETCH_WORKERS = int(os.getenv("FETCH_WORKERS", "10"))
AI_WORKERS = int(os.getenv("AI_WORKERS", "4"))
IGNORE_SEEN = os.getenv("IGNORE_SEEN", "0").lower() in {"1", "true", "yes", "y"}
ROLLING_DAYS = int(os.getenv("ROLLING_DAYS", "7"))

IDENTITY = [
    "dei","diversity","equity","inclusion","anti-woke","woke","transgender",
    "gender ideology","pronoun","trans rights","trans student","trans athlete",
    "drag","pride","lgbt","lgbtq","book ban","banned books","library",
    "school board","parents' rights","parents rights","voucher","school choice",
    "religious liberty","christian values","traditional values","western civilization",
    "white people","white boys","young white men","muslim","islamic","muslim school",
    "islamic school","immigrant","immigration","refugee","illegal alien","cair","sharia"
]
OUTRAGE = [
    "backlash","outrage","criticized","criticizes","slams","targets","opposes","ban",
    "bans","blocks","defund","exclude","excluded","remove","pull funding","lawsuit",
    "sues","debate","hearing","boycott","pressure campaign"
]
ACTORS = [
    "maga","trump","republican","republicans","gop","conservative","conservatives",
    "fox news","moms for liberty","charlie kirk","erika kirk","governor",
    "attorney general","state lawmakers","christian nationalist"
]
CRIME = [
    "shooting","shot","shot up","gunman","gunfire","opened fire","murder",
    "murdered","killed","dead","injured","wounded","bombing","terror","terrorist",
    "arrested","charged with","indicted","convicted","sentenced","assault","attacked",
    "attack","rape","sexual assault","trafficking","abuse","homicide","stabbing","stabbed"
]
SCANDAL = [
    "fake electors","alternate electors","electors","election fraud","campaign finance",
    "bribery","corruption","indictment","prosecution","felony","embezzlement"
]

SECTION_PAGES = [
    ("index.html", "Front Page"),
    ("education.html", "Education & Schools"),
    ("gender.html", "Gender & Sexuality"),
    ("religion.html", "Religion & Pluralism"),
    ("race.html", "Race, DEI & Immigration"),
    ("wings.html", "In the Wings"),
]

def load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path: Path | str, payload) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()

def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url

def build_google_news_rss(query: str) -> str:
    quoted = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={quoted}+when:{ROLLING_DAYS}d&hl=en-US&gl=US&ceid=US:en"

def parse_date(entry) -> str:
    for raw in (getattr(entry, "published", None), getattr(entry, "updated", None), getattr(entry, "created", None)):
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(dt.timezone.utc).isoformat()
            except Exception:
                pass
    return dt.datetime.now(dt.timezone.utc).isoformat()

def is_within_days(iso_str: str, days: int) -> bool:
    try:
        d = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        return d >= cutoff
    except Exception:
        return False

def term_matches(term: str, blob: str) -> bool:
    term = term.lower().strip()
    blob = blob.lower()
    if " " in term or "-" in term or "'" in term:
        return term in blob
    return re.search(rf"\b{re.escape(term)}\b", blob) is not None

def collect_matches(terms: list[str], blob: str) -> list[str]:
    return [term for term in terms if term_matches(term, blob)]

def load_feed_specs() -> list[dict]:
    cfg = load_json(CONFIG_FILE, {})
    out = []
    for item in cfg.get("rss_feeds", []):
        if item.get("enabled", True):
            out.append({"label": item["label"], "url": item["url"], "state": item.get("state")})
    for item in cfg.get("google_news_queries", []):
        if item.get("enabled", True):
            out.append({"label": item["label"], "url": build_google_news_rss(item["query"]), "state": item.get("state")})
    return out

def analyze_text(text: str) -> dict:
    t = (text or "").lower()
    i = collect_matches(IDENTITY, t)
    o = collect_matches(OUTRAGE, t)
    a = collect_matches(ACTORS, t)
    c = collect_matches(CRIME, t)
    s = collect_matches(SCANDAL, t)
    score = round(len(i) * 1.8 + len(o) * 1.0 + len(a) * 0.8 - len(c) * 2.5 - len(s) * 2.6, 1)
    schoolish = any(term_matches(x, t) for x in [
        "school", "schools", "school board", "curriculum", "library",
        "book ban", "banned books", "voucher", "religious liberty",
        "parents' rights", "parents rights"
    ])
    maybe = (
        ((i and o) or (i and a) or len(i) >= 2 or (score >= 2.2 and i))
        or (schoolish and (i or o or a))
        or (len(i) >= 1 and len(o) >= 1)
        or (len(i) >= 1 and len(a) >= 1)
    ) and len(c) < 1 and not (s and not i)
    return {"maybe_relevant": maybe, "lexical_score": score}

def article_key(item: dict) -> str:
    return normalize_url(item.get("url")) or re.sub(r"\W+", "-", item.get("title", "").lower()).strip("-")

def fetch_candidates(spec: dict) -> list[dict]:
    parsed = feedparser.parse(spec["url"])
    entries = getattr(parsed, "entries", [])[:MAX_CANDIDATES_PER_FEED]
    out = []
    for entry in entries:
        title = strip_html(getattr(entry, "title", ""))
        summary = strip_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        url = normalize_url(getattr(entry, "link", ""))
        if not title or not url:
            continue
        published = parse_date(entry)
        if not is_within_days(published, ROLLING_DAYS):
            continue
        analysis = analyze_text(title + "\n" + summary)
        if not analysis["maybe_relevant"]:
            continue
        out.append({
            "title": title, "url": url, "summary": summary[:1000], "published": published,
            "source": spec["label"], "state": spec.get("state"), "prefilter": analysis,
        })
    return out

def format_date(iso_str: str) -> str:
    try:
        d = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return d.strftime("%b %d, %Y")
    except Exception:
        return ""

def story_card(item: dict, compact: bool = False) -> str:
    tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in item.get("tags", [])[:4])
    cls = "story-card compact" if compact else "story-card"
    summary_html = "" if compact else f'<p class="summary">{html.escape(item.get("summary", ""))}</p>'
    tags_html = "" if compact else f'<div class="tags">{tags}</div>'
    return (
        f'<article class="{cls}"><div class="story-meta">'
        f'<span class="angle">{html.escape(item.get("angle", "identity-outrage story"))}</span>'
        f'<span>{html.escape(item.get("state") or "US")}</span>'
        f'<span>{html.escape(format_date(item.get("published", "")))}</span>'
        f'<span>score {float(item.get("score", 0)):.1f}</span></div>'
        f'<h3><a href="{html.escape(item.get("url", ""))}" target="_blank" rel="noopener noreferrer">{html.escape(item.get("title", ""))}</a></h3>'
        f'{summary_html}{tags_html}<div class="source">{html.escape(item.get("source", ""))}</div></article>'
    )

def render_lead(lead: dict | None, side_items: list[dict]) -> str:
    if not lead:
        return '<section class="lead-grid"><article class="lead-story"><h2>No lead story yet</h2><p>Run the pipeline to generate the next edition.</p></article></section>'
    lead_tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in lead.get("tags", [])[:5])
    right = "".join(story_card(x, compact=True) for x in side_items) or '<article class="story-card compact"><h3>No secondary stories</h3></article>'
    return (
        '<section class="lead-grid"><article class="lead-story"><div class="eyebrow">Lead story</div>'
        f'<div class="story-meta"><span class="angle">{html.escape(lead.get("angle", "identity-outrage story"))}</span>'
        f'<span>{html.escape(lead.get("state") or "US")}</span>'
        f'<span>{html.escape(format_date(lead.get("published", "")))}</span>'
        f'<span>score {float(lead.get("score", 0)):.1f}</span></div>'
        f'<h2><a href="{html.escape(lead.get("url", ""))}" target="_blank" rel="noopener noreferrer">{html.escape(lead.get("title", ""))}</a></h2>'
        f'<p>{html.escape(lead.get("summary", ""))}</p><div class="tags">{lead_tags}</div>'
        f'<div class="source">{html.escape(lead.get("source", ""))}</div></article>'
        f'<div class="lead-side">{right}</div></section>'
    )

def render_section(title: str, subtitle: str, items: list[dict], compact: bool = False) -> str:
    body = "".join(story_card(x, compact=compact) for x in items) if items else '<article class="story-card empty"><h3>Nothing in this section this run</h3></article>'
    extra = " compact-grid" if compact else ""
    return f'<section class="section"><div class="section-head"><div><h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p></div></div><div class="grid{extra}">{body}</div></section>'

def dedupe_rows(items: list[dict]) -> list[dict]:
    out, seen = [], set()
    for item in items:
        key = article_key(item)
        title_key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
        if key in seen or title_key in seen:
            continue
        seen.add(key)
        seen.add(title_key)
        out.append(item)
    return out

def section_name(item: dict) -> str:
    tags = set(item.get("tags", []))
    angle = (item.get("angle") or "").lower()
    blob = " ".join([item.get("title", ""), item.get("summary", ""), angle]).lower()
    if {"book-bans", "parents-rights"} & tags or any(x in blob for x in ["school", "curriculum", "school board", "library", "voucher"]):
        return "Education & Schools"
    if {"anti-trans", "lgbtq-panic"} & tags or any(x in blob for x in ["transgender", "gender ideology", "pronoun", "drag", "pride"]):
        return "Gender & Sexuality"
    if {"anti-muslim", "religious-liberty"} & tags or any(x in blob for x in ["muslim", "islamic school", "religious liberty", "christian values", "traditional values"]):
        return "Religion & Pluralism"
    if {"anti-dei", "white-grievance", "immigration"} & tags or any(x in blob for x in ["dei", "diversity", "equity", "white people", "white boys", "immigrant", "immigration", "refugee"]):
        return "Race, DEI & Immigration"
    return "Top Stories"

def build_sections(kept: list[dict]) -> dict:
    lead = kept[0] if kept else None
    remainder = kept[1:] if len(kept) > 1 else []
    top_story_pool = remainder[:8]
    lead_side = top_story_pool[:4]
    top_stories = top_story_pool[4:8]
    used_keys = {article_key(x) for x in top_story_pool}
    remaining_for_sections = [x for x in remainder if article_key(x) not in used_keys]
    sections = {"Education & Schools": [], "Gender & Sexuality": [], "Religion & Pluralism": [], "Race, DEI & Immigration": []}
    for item in remaining_for_sections:
        sections.setdefault(section_name(item), []).append(item)
    return {
        "lead": lead, "lead_side": lead_side, "top_stories": top_stories,
        "education": sections["Education & Schools"][:16],
        "gender": sections["Gender & Sexuality"][:16],
        "religion": sections["Religion & Pluralism"][:16],
        "race": sections["Race, DEI & Immigration"][:16],
    }

def nav_html(current_file: str) -> str:
    links = []
    for filename, label in SECTION_PAGES:
        cls = ' class="current"' if filename == current_file else ""
        links.append(f'<a href="{filename}"{cls}>{html.escape(label)}</a>')
    return '<nav class="section-nav" aria-label="Sections">' + "".join(links) + '</nav>'

def page_shell(title: str, current_file: str, main_html: str, payload: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} - National Association of Worried White People</title>
<meta name="description" content="Tracking fear-based narratives, misinformation, and identity grievance in U.S. politics, media, education, and public life.">
<link rel="icon" type="image/png" href="images/nawwp_favicon_256.png">
<style>
:root{{--bg:#f5f1e8;--paper:#fffdf9;--ink:#151515;--muted:#666;--line:#ddd3c4;--accent:#931b1d;--tag:#f3e7d5}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Georgia,"Times New Roman",serif}}
.wrap{{max-width:1420px;margin:0 auto;padding:0 22px 70px}}
.topbar{{border-bottom:1px solid var(--line);padding:14px 0 10px;color:var(--muted);font:13px/1.4 Arial,Helvetica,sans-serif;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}
.hero-image{{margin:14px 0 10px;text-align:center}}
.hero-image img{{width:100%;max-width:1200px;height:auto;display:inline-block;border:1px solid #cdbfa9;box-shadow:0 3px 18px rgba(0,0,0,.06);background:#fffdf9}}
.deck{{max-width:980px;color:#3d3d3d;font-size:21px;line-height:1.45;margin:0 0 14px}}
.section-nav{{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:12px 0;margin:0 0 20px;font:700 12px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.10em;text-transform:uppercase;display:flex;gap:18px;flex-wrap:wrap}}
.section-nav a{{color:var(--ink);text-decoration:none}}
.section-nav a.current{{color:var(--accent)}}
.section-nav a:hover{{text-decoration:underline;color:var(--accent)}}
.lead-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);gap:24px}}
.lead-story,.story-card{{background:var(--paper);border:1px solid var(--line);box-shadow:0 2px 14px rgba(0,0,0,.04)}}
.lead-story{{padding:24px 26px}}
.lead-story h2{{font-size:42px;line-height:1.05;margin:10px 0 12px}}
.lead-story p{{font-size:20px;line-height:1.5;color:#2d2d2d}}
.lead-side{{display:grid;gap:16px}}
.story-card{{padding:18px 20px}}
.story-card.compact h3{{font-size:24px}}
.story-card h3{{margin:8px 0 10px;font-size:28px;line-height:1.12}}
.story-card a,.lead-story a{{color:inherit;text-decoration:none}}
.story-card a:hover,.lead-story a:hover{{text-decoration:underline}}
.story-meta{{display:flex;gap:10px;flex-wrap:wrap;font:13px/1.4 Arial,Helvetica,sans-serif;color:var(--muted)}}
.story-meta .angle{{color:var(--accent);font-weight:700}}
.eyebrow{{font:700 11px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}}
.summary{{margin:0 0 12px;color:#2c2c2c}}
.tags{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}
.tag{{background:var(--tag);border:1px solid #e4d3b8;border-radius:999px;padding:5px 9px;font:12px/1.2 Arial,Helvetica,sans-serif;color:#6a4b20}}
.source{{margin-top:12px;font:13px/1.4 Arial,Helvetica,sans-serif;color:var(--muted)}}
.section{{margin-top:34px}}
.section-head{{display:flex;justify-content:space-between;gap:16px;align-items:end;border-top:3px solid var(--ink);padding-top:12px;margin-bottom:14px}}
.section h2{{margin:0;font-size:34px}}
.section p{{margin:0;color:var(--muted);font:15px/1.4 Arial,Helvetica,sans-serif}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}}
.compact-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}
.footer{{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);font:14px/1.5 Arial,Helvetica,sans-serif;color:var(--muted)}}
@media (max-width:980px){{.lead-grid{{grid-template-columns:1fr}}.grid,.compact-grid{{grid-template-columns:1fr}}.lead-story h2{{font-size:34px}}.deck{{font-size:18px}}}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div>National Association of Worried White People</div>
    <div>Latest edition · <span id="latest-edition-time" data-generated="{html.escape(payload["generated_at"])}">loading…</span></div>
  </div>
  <div class="hero-image"><img src="images/nawwp_masthead_social_1200w.png" alt="NAWWP masthead"></div>
  <div class="deck">Tracking fear-based narratives, misinformation, and identity grievance in U.S. politics, media, education, and public life.</div>
  {nav_html(current_file)}
  {main_html}
  <div class="footer">Generated automatically from RSS and Google News RSS sources. Stories remain visible for a rolling 7-day window and age out automatically.</div>
</div>
<script>
(function () {{
  const el = document.getElementById("latest-edition-time");
  if (!el) return;
  const raw = el.getAttribute("data-generated");
  const d = new Date(raw);
  if (isNaN(d.getTime())) {{ el.textContent = raw; return; }}
  el.textContent = d.toLocaleString([], {{year:"numeric",month:"long",day:"numeric",hour:"numeric",minute:"2-digit"}});
}})();
</script>
</body>
</html>"""

def build_page_html(payload: dict) -> dict:
    kept = payload["kept"]
    wings = payload["in_the_wings"]
    parts = build_sections(kept)
    front_main = (
        render_lead(parts["lead"], parts["lead_side"])
        + render_section("Top Stories", "The strongest stories in the current 7-day window.", parts["top_stories"], compact=True)
        + render_section("Education & Schools", "Book bans, curriculum fights, DEI in schools, school boards, and parents’ rights campaigns.", parts["education"][:6])
        + render_section("Gender & Sexuality", "Anti-trans panic, drag and pride backlash, pronoun fights, and gender-based outrage politics.", parts["gender"][:6])
        + render_section("Religion & Pluralism", "Muslim school targeting, religious-liberty weaponization, and pluralism backlash.", parts["religion"][:6])
        + render_section("Race, DEI & Immigration", "Anti-DEI backlash, white grievance rhetoric, and immigrant or refugee panic narratives.", parts["race"][:6])
        + render_section("In the Wings", "Borderline or adjacent stories from the last 7 days.", wings[:12], compact=True)
    )
    return {
        "index.html": page_shell("Front Page", "index.html", front_main, payload),
        "education.html": page_shell("Education & Schools", "education.html", render_section("Education & Schools", "Book bans, curriculum fights, DEI in schools, school boards, and parents’ rights campaigns.", parts["education"]), payload),
        "gender.html": page_shell("Gender & Sexuality", "gender.html", render_section("Gender & Sexuality", "Anti-trans panic, drag and pride backlash, pronoun fights, and gender-based outrage politics.", parts["gender"]), payload),
        "religion.html": page_shell("Religion & Pluralism", "religion.html", render_section("Religion & Pluralism", "Muslim school targeting, religious-liberty weaponization, and pluralism backlash.", parts["religion"]), payload),
        "race.html": page_shell("Race, DEI & Immigration", "race.html", render_section("Race, DEI & Immigration", "Anti-DEI backlash, white grievance rhetoric, and immigrant or refugee panic narratives.", parts["race"]), payload),
        "wings.html": page_shell("In the Wings", "wings.html", render_section("In the Wings", "Borderline or adjacent stories from the last 7 days.", wings[:40], compact=True), payload),
    }

def write_pages(payload: dict) -> None:
    for filename, content in build_page_html(payload).items():
        (DOCS_DIR / filename).write_text(content, encoding="utf-8")

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
    raw.sort(key=lambda x: (x["prefilter"]["lexical_score"], x.get("published", "")), reverse=True)
    candidates = []
    seen_local = set()
    for item in raw:
        key = article_key(item)
        title_key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
        if not IGNORE_SEEN and (key in seen or title_key in seen):
            continue
        if key in seen_local or title_key in seen_local:
            continue
        seen_local.add(key); seen_local.add(title_key); candidates.append(item)
    candidates = candidates[:MAX_AI_REVIEWS_PER_RUN]
    reviewed, current_kept, current_wings, current_rejected = [], [], [], []
    with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
        futures = {ex.submit(evaluate_article, item): item for item in candidates}
        for fut in as_completed(futures):
            item = futures[fut]
            row = {**item, **fut.result()}
            reviewed.append(row)
            score = float(row.get("score", 0))
            bucket = row.get("bucket", "reject")
            if bucket == "keep" and score >= KEEP_MIN_SCORE:
                current_kept.append(row)
            elif bucket in {"keep", "wings"} and score >= WINGS_MIN_SCORE:
                if bucket == "keep":
                    row["bucket"] = "wings"
                current_wings.append(row)
            else:
                current_rejected.append(row)
    for item in reviewed:
        seen.add(article_key(item))
        seen.add(re.sub(r"\W+", " ", item.get("title", "").lower()).strip())
    review_rows = [{
        "title": r.get("title"), "url": r.get("url"), "source": r.get("source"), "state": r.get("state"),
        "bucket": r.get("bucket"), "score": r.get("score"), "tags": r.get("tags", []),
        "angle": r.get("angle"), "summary": r.get("summary"), "reason": r.get("reason"),
        "published": r.get("published"),
    } for r in reviewed]
    reviews.extend(review_rows); reviews = reviews[-8000:]
    archived_kept = [r for r in reviews if r.get("bucket") == "keep" and is_within_days(r.get("published", ""), ROLLING_DAYS)]
    archived_wings = [r for r in reviews if r.get("bucket") == "wings" and is_within_days(r.get("published", ""), ROLLING_DAYS)]
    merged_kept = sorted(dedupe_rows(current_kept + archived_kept), key=lambda x: (float(x.get("score", 0)), x.get("published", "")), reverse=True)
    merged_wings = sorted(dedupe_rows(current_wings + archived_wings), key=lambda x: (float(x.get("score", 0)), x.get("published", "")), reverse=True)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "counts": {
            "kept": len(merged_kept), "wings": len(merged_wings), "rejected": len(current_rejected),
            "reviewed": len(reviewed), "new_kept_this_run": len(current_kept),
            "new_wings_this_run": len(current_wings), "rolling_days": ROLLING_DAYS,
        },
        "kept": merged_kept, "in_the_wings": merged_wings,
        "rejected": sorted(current_rejected, key=lambda x: x.get("score", 0), reverse=True)[:200],
    }
    save_json(ARCHIVE_FILE, {"seen": sorted(seen), "reviews": reviews})
    save_json(OUTPUT_FILE, payload)
    write_pages(payload)
    print(f"Reviewed this run: {len(reviewed)}")
    print(f"Published rolling window: kept={len(merged_kept)} wings={len(merged_wings)} days={ROLLING_DAYS}")
    for filename, _ in SECTION_PAGES:
        print(f"Saved {DOCS_DIR / filename}")
    print(f"Saved {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

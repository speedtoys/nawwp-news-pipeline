
#!/usr/bin/env python3
import datetime as dt, html, json, os, re, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from pathlib import Path
import feedparser
from score_articles import evaluate_article

CONFIG_FILE="rss_sources.json"; ARCHIVE_FILE="archive.json"; DOCS_DIR=Path("docs"); OUTPUT_FILE=DOCS_DIR/"news.json"
MAX_CANDIDATES_PER_FEED=int(os.getenv("MAX_CANDIDATES_PER_FEED","100")); MAX_AI_REVIEWS_PER_RUN=int(os.getenv("MAX_AI_REVIEWS_PER_RUN","420"))
KEEP_MIN_SCORE=float(os.getenv("KEEP_MIN_SCORE","4.0")); WINGS_MIN_SCORE=float(os.getenv("WINGS_MIN_SCORE","2.5"))
FETCH_WORKERS=int(os.getenv("FETCH_WORKERS","12")); AI_WORKERS=int(os.getenv("AI_WORKERS","4"))
IGNORE_SEEN=os.getenv("IGNORE_SEEN","0").lower() in {"1","true","yes","y"}; ROLLING_DAYS=int(os.getenv("ROLLING_DAYS","30")); NOT_A_TRANS_START=os.getenv("NOT_A_TRANS_START","2025-01-20")
IDENTITY=["dei","diversity","equity","inclusion","anti-woke","woke","transgender","gender ideology","pronoun","trans rights","trans student","trans athlete","drag","pride","lgbt","lgbtq","book ban","banned books","library","school board","parents' rights","parents rights","voucher","school choice","religious liberty","christian values","traditional values","western civilization","white people","white boys","young white men","muslim","islamic","muslim school","islamic school","immigrant","immigration","refugee","illegal alien","cair","sharia"]
OUTRAGE=["backlash","outrage","criticized","criticizes","slams","targets","opposes","ban","bans","blocks","defund","exclude","excluded","remove","pull funding","lawsuit","sues","debate","hearing","boycott","pressure campaign"]
ACTORS=["maga","trump","republican","republicans","gop","conservative","conservatives","governor","attorney general","state lawmakers"]
SPECIAL_CRIME=["rape","sexual assault","sex abuse","sexual abuse","child sexual abuse","molestation","molested","child pornography","csam","exploitation","grooming","solicitation","sentenced","convicted","arrested","charged with","guilty plea","pleaded guilty"]
SPECIAL_ACTORS=["republican","gop","maga","conservative","pastor","priest","church","church leader","youth pastor","minister","deacon","christian school","family values","parents' rights","anti-lgbt","anti-trans","religious leader"]
LAW_ORDER_ACTORS=["trump administration","federal agency","republican governor","republican attorney general","republican legislature","republican sheriff","republican county","republican school board","republican mayor","republican official","gop official","republican legislator","republican officeholder","trump adviser","trump official","republican county clerk","attorney general","governor","sheriff","mayor","county clerk","school board"]
LAW_ORDER_EVENTS=["court order","injunction","ruling","judge ordered","unconstitutional","unlawful","illegal","contempt","settlement","civil penalty","civil penalties","consent decree","damages","sanctions","sanctioned","blocked by court","ethics violation","ethics finding","indicted","charged","convicted","sentenced","pleaded guilty","guilty plea"]
GENERAL_CRIME=["shooting","shot","shot up","gunman","gunfire","opened fire","murder","murdered","killed","dead","injured","wounded","bombing","terror","terrorist","arrested","charged with","indicted","convicted","sentenced","assault","attacked","attack","rape","sexual assault","trafficking","abuse","homicide","stabbing","stabbed"]
SCANDAL=["fake electors","alternate electors","electors","election fraud","campaign finance","bribery","corruption","indictment","prosecution","felony","embezzlement"]
SECTION_PAGES=[("index.html","Front Page"),("education.html","Education & Schools"),("gender.html","Gender & Sexuality"),("religion.html","Religion & Pluralism"),("race.html","Race, DEI & Immigration"),("law-and-order.html","Law & Order"),("not-a-trans.html","Not A Trans…"),("wings.html","In the Wings")]

def load_json(path, default):
    p=Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default
def save_json(path,payload): Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
def strip_html(text): return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",text or ""))).strip()
def normalize_url(url): return ("https://"+url[len("http://"):]) if (url or "").startswith("http://") else (url or "").strip()
def build_google_news_rss(query,special=False):
    q=urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}+after:{NOT_A_TRANS_START}&hl=en-US&gl=US&ceid=US:en" if special else f"https://news.google.com/rss/search?q={q}+when:{ROLLING_DAYS}d&hl=en-US&gl=US&ceid=US:en"
def parse_date(entry):
    for raw in (getattr(entry,"published",None),getattr(entry,"updated",None),getattr(entry,"created",None)):
        if raw:
            try: return parsedate_to_datetime(raw).astimezone(dt.timezone.utc).isoformat()
            except Exception: pass
    return dt.datetime.now(dt.timezone.utc).isoformat()
def parse_iso(s):
    try: return dt.datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception: return None
def is_within_days(s,days):
    d=parse_iso(s); return bool(d and d >= (dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days)))
def is_after_fixed_start(s,start):
    d=parse_iso(s); return bool(d and d >= dt.datetime.fromisoformat(start+"T00:00:00+00:00"))
def term_matches(term,blob):
    term=term.lower().strip(); blob=blob.lower()
    if " " in term or "-" in term or "'" in term: return term in blob
    return re.search(rf"\b{re.escape(term)}\b", blob) is not None
def collect_matches(terms,blob): return [t for t in terms if term_matches(t,blob)]
def analyze_text(text):
    t=(text or "").lower(); i=collect_matches(IDENTITY,t); o=collect_matches(OUTRAGE,t); a=collect_matches(ACTORS,t)
    gc=collect_matches(GENERAL_CRIME,t); sc=collect_matches(SPECIAL_CRIME,t); sa=collect_matches(SPECIAL_ACTORS,t); la=collect_matches(LAW_ORDER_ACTORS,t); le=collect_matches(LAW_ORDER_EVENTS,t); s=collect_matches(SCANDAL,t)
    score=round(len(i)*1.8+len(o)*1.0+len(a)*0.8+len(la)*1.0+len(le)*1.0-len(gc)*2.5-len(s)*2.6,1)
    schoolish=any(term_matches(x,t) for x in ["school","schools","school board","curriculum","library","book ban","banned books","voucher","religious liberty","parents' rights","parents rights"])
    maybe_general=((((i and o) or (i and a) or len(i)>=2 or (score>=2.2 and i)) or (schoolish and (i or o or a)) or (len(i)>=1 and len(o)>=1) or (len(i)>=1 and len(a)>=1)) and len(gc)<1 and not (s and not i))
    return {"maybe_relevant": maybe_general, "maybe_special": bool(sc and sa), "maybe_law": bool(la and le), "lexical_score": score}
def article_key(item): return normalize_url(item.get("url")) or re.sub(r"\W+","-",item.get("title","").lower()).strip("-")
def load_feed_specs():
    cfg=load_json(CONFIG_FILE,{})
    out=[]
    for item in cfg.get("rss_feeds",[]):
        if item.get("enabled",True): out.append({"label":item["label"],"url":item["url"],"state":item.get("state"),"special":False})
    for item in cfg.get("google_news_queries",[]):
        if item.get("enabled",True): out.append({"label":item["label"],"url":build_google_news_rss(item["query"],False),"state":item.get("state"),"special":False})
    for item in cfg.get("google_news_queries_special",[]):
        if item.get("enabled",True): out.append({"label":item["label"],"url":build_google_news_rss(item["query"],True),"state":item.get("state"),"special":True})
    return out
def fetch_candidates(spec):
    parsed=feedparser.parse(spec["url"]); entries=getattr(parsed,"entries",[])[:MAX_CANDIDATES_PER_FEED]; out=[]
    for entry in entries:
        title=strip_html(getattr(entry,"title","")); summary=strip_html(getattr(entry,"summary","") or getattr(entry,"description","")); url=normalize_url(getattr(entry,"link",""))
        if not title or not url: continue
        published=parse_date(entry); analysis=analyze_text(title+"\n"+summary)
        if spec.get("special"):
            if not is_after_fixed_start(published,NOT_A_TRANS_START): continue
            if not (analysis["maybe_special"] or analysis["maybe_law"]): continue
        else:
            if not is_within_days(published,ROLLING_DAYS): continue
            if not (analysis["maybe_relevant"] or analysis["maybe_law"]): continue
        out.append({"title":title,"url":url,"summary":summary[:1000],"published":published,"source":spec["label"],"state":spec.get("state"),"special_query":spec.get("special",False),"prefilter":analysis})
    return out
def format_date(s):
    d=parse_iso(s); return d.strftime("%b %d, %Y") if d else ""
def story_card(item,compact=False):
    tags="".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in item.get("tags",[])[:4]); cls="story-card compact" if compact else "story-card"; summary_html="" if compact else f'<p class="summary">{html.escape(item.get("summary",""))}</p>'; tags_html="" if compact else f'<div class="tags">{tags}</div>'
    return f'<article class="{cls}"><div class="story-meta"><span class="angle">{html.escape(item.get("angle","identity-outrage story"))}</span><span>{html.escape(item.get("state") or "US")}</span><span>{html.escape(format_date(item.get("published","")))}</span><span>score {float(item.get("score",0)):.1f}</span></div><h3><a href="{html.escape(item.get("url",""))}" target="_blank" rel="noopener noreferrer">{html.escape(item.get("title",""))}</a></h3>{summary_html}{tags_html}<div class="source">{html.escape(item.get("source",""))}</div></article>'
def render_lead(lead,side_items):
    if not lead: return '<section class="lead-grid"><article class="lead-story"><h2>No lead story yet</h2><p>Run the pipeline to generate the next edition.</p></article></section>'
    lead_tags="".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in lead.get("tags",[])[:5]); right="".join(story_card(x,compact=True) for x in side_items) or '<article class="story-card compact"><h3>No secondary stories</h3></article>'
    return f'<section class="lead-grid"><article class="lead-story"><div class="eyebrow">Lead story</div><div class="story-meta"><span class="angle">{html.escape(lead.get("angle","identity-outrage story"))}</span><span>{html.escape(lead.get("state") or "US")}</span><span>{html.escape(format_date(lead.get("published","")))}</span><span>score {float(lead.get("score",0)):.1f}</span></div><h2><a href="{html.escape(lead.get("url",""))}" target="_blank" rel="noopener noreferrer">{html.escape(lead.get("title",""))}</a></h2><p>{html.escape(lead.get("summary",""))}</p><div class="tags">{lead_tags}</div><div class="source">{html.escape(lead.get("source",""))}</div></article><div class="lead-side">{right}</div></section>'
def render_section(title,subtitle,items,compact=False):
    body="".join(story_card(x,compact=compact) for x in items) if items else '<article class="story-card empty"><h3>Nothing in this section this run</h3></article>'; extra=" compact-grid" if compact else ""
    return f'<section class="section"><div class="section-head"><div><h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p></div></div><div class="grid{extra}">{body}</div></section>'
def dedupe_rows(items):
    out=[]; seen=set()
    for item in items:
        key=article_key(item); title_key=re.sub(r"\W+"," ",item.get("title","").lower()).strip()
        if key in seen or title_key in seen: continue
        seen.add(key); seen.add(title_key); out.append(item)
    return out
def section_name(item):
    if item.get("bucket")=="not_a_trans": return "Not A Trans…"
    if item.get("bucket")=="law_and_order": return "Law & Order"
    tags=set(item.get("tags",[])); angle=(item.get("angle") or "").lower(); blob=" ".join([item.get("title",""),item.get("summary",""),angle]).lower()
    if any(x in tags for x in {"book-bans","parents-rights"}) or any(x in blob for x in ["school","curriculum","school board","library","voucher"]): return "Education & Schools"
    if any(x in tags for x in {"anti-trans","lgbtq-panic"}) or any(x in blob for x in ["transgender","gender ideology","pronoun","drag","pride"]): return "Gender & Sexuality"
    if any(x in tags for x in {"anti-muslim","religious-liberty"}) or any(x in blob for x in ["muslim","islamic school","religious liberty","christian values","traditional values"]): return "Religion & Pluralism"
    if any(x in tags for x in {"anti-dei","white-grievance","immigration"}) or any(x in blob for x in ["dei","diversity","equity","white people","white boys","immigrant","immigration","refugee"]): return "Race, DEI & Immigration"
    return "Top Stories"
def build_sections(kept,law_and_order,not_a_trans):
    lead=kept[0] if kept else None; remainder=kept[1:] if len(kept)>1 else []; top_story_pool=remainder[:8]; lead_side=top_story_pool[:4]; top_stories=top_story_pool[4:8]; used_keys={article_key(x) for x in top_story_pool}; remaining_for_sections=[x for x in remainder if article_key(x) not in used_keys]; sections={"Education & Schools":[],"Gender & Sexuality":[],"Religion & Pluralism":[],"Race, DEI & Immigration":[]}
    for item in remaining_for_sections:
        sec=section_name(item)
        if sec in sections: sections[sec].append(item)
    return {"lead":lead,"lead_side":lead_side,"top_stories":top_stories,"education":sections["Education & Schools"][:16],"gender":sections["Gender & Sexuality"][:16],"religion":sections["Religion & Pluralism"][:16],"race":sections["Race, DEI & Immigration"][:16],"law_and_order":law_and_order[:40],"not_a_trans":not_a_trans[:40]}
def nav_html(current_file):
    links=[]
    for filename,label in SECTION_PAGES:
        cls=' class="current"' if filename==current_file else ""
        links.append(f'<a href="{filename}"{cls}>{html.escape(label)}</a>')
    return '<nav class="section-nav" aria-label="Sections">'+"".join(links)+'</nav>'
def page_shell(title,current_file,main_html,payload):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)} - National Association of Worried White People</title><meta name="description" content="Tracking fear-based narratives, misinformation, and identity grievance in U.S. politics, media, education, and public life."><link rel="icon" type="image/png" href="images/nawwp_favicon_256.png"><style>
:root{{--bg:#f5f1e8;--paper:#fffdf9;--ink:#151515;--muted:#666;--line:#ddd3c4;--accent:#931b1d;--tag:#f3e7d5}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Georgia,"Times New Roman",serif}}.wrap{{max-width:1420px;margin:0 auto;padding:0 22px 70px}}.topbar{{border-bottom:1px solid var(--line);padding:14px 0 10px;color:var(--muted);font:13px/1.4 Arial,Helvetica,sans-serif;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}.hero-image{{margin:14px 0 10px;text-align:center}}.hero-image img{{width:100%;max-width:1200px;height:auto;display:inline-block;border:1px solid #cdbfa9;box-shadow:0 3px 18px rgba(0,0,0,.06);background:#fffdf9}}.deck{{max-width:980px;color:#3d3d3d;font-size:21px;line-height:1.45;margin:0 0 14px}}.section-nav{{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:12px 0;margin:0 0 20px;font:700 12px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.10em;text-transform:uppercase;display:flex;gap:18px;flex-wrap:wrap}}.section-nav a{{color:var(--ink);text-decoration:none}}.section-nav a.current{{color:var(--accent)}}.section-nav a:hover{{text-decoration:underline;color:var(--accent)}}.lead-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);gap:24px}}.lead-story,.story-card{{background:var(--paper);border:1px solid var(--line);box-shadow:0 2px 14px rgba(0,0,0,.04)}}.lead-story{{padding:24px 26px}}.lead-story h2{{font-size:42px;line-height:1.05;margin:10px 0 12px}}.lead-story p{{font-size:20px;line-height:1.5;color:#2d2d2d}}.lead-side{{display:grid;gap:16px}}.story-card{{padding:18px 20px}}.story-card.compact h3{{font-size:24px}}.story-card h3{{margin:8px 0 10px;font-size:28px;line-height:1.12}}.story-card a,.lead-story a{{color:inherit;text-decoration:none}}.story-card a:hover,.lead-story a:hover{{text-decoration:underline}}.story-meta{{display:flex;gap:10px;flex-wrap:wrap;font:13px/1.4 Arial,Helvetica,sans-serif;color:var(--muted)}}.story-meta .angle{{color:var(--accent);font-weight:700}}.eyebrow{{font:700 11px/1.2 Arial,Helvetica,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}}.summary{{margin:0 0 12px;color:#2c2c2c}}.tags{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.tag{{background:var(--tag);border:1px solid #e4d3b8;border-radius:999px;padding:5px 9px;font:12px/1.2 Arial,Helvetica,sans-serif;color:#6a4b20}}.source{{margin-top:12px;font:13px/1.4 Arial,Helvetica,sans-serif;color:var(--muted)}}.section{{margin-top:34px}}.section-head{{display:flex;justify-content:space-between;gap:16px;align-items:end;border-top:3px solid var(--ink);padding-top:12px;margin-bottom:14px}}.section h2{{margin:0;font-size:34px}}.section p{{margin:0;color:var(--muted);font:15px/1.4 Arial,Helvetica,sans-serif}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}}.compact-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.footer{{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);font:14px/1.5 Arial,Helvetica,sans-serif;color:var(--muted)}}@media (max-width:980px){{.lead-grid{{grid-template-columns:1fr}}.grid,.compact-grid{{grid-template-columns:1fr}}.lead-story h2{{font-size:34px}}.deck{{font-size:18px}}}}
</style></head><body><div class="wrap"><div class="topbar"><div>National Association of Worried White People</div><div>Latest edition · <span id="latest-edition-time" data-generated="{html.escape(payload["generated_at"])}">loading…</span></div></div><div class="hero-image"><img src="images/nawwp_masthead_social_1200w.png" alt="NAWWP masthead"></div><div class="deck">Tracking fear-based narratives, misinformation, and identity grievance in U.S. politics, media, education, and public life.</div>{nav_html(current_file)}{main_html}<div class="footer">General sections use a rolling 30-day window. “Not A Trans…” uses a dedicated archive window beginning {html.escape(NOT_A_TRANS_START)} and stays isolated to its own section. “Law & Order” tracks documented legal actions against Republican governments and Republican office holders.</div></div><script>(function(){{const el=document.getElementById("latest-edition-time");if(!el)return;const raw=el.getAttribute("data-generated");const d=new Date(raw);if(isNaN(d.getTime())){{el.textContent=raw;return;}}el.textContent=d.toLocaleString([],{{year:"numeric",month:"long",day:"numeric",hour:"numeric",minute:"2-digit"}});}})();</script></body></html>"""
def build_page_html(payload):
    kept=payload["kept"]; wings=payload["in_the_wings"]; not_a_trans=payload["not_a_trans"]; law_and_order=payload["law_and_order"]; parts=build_sections(kept,law_and_order,not_a_trans)
    front_main=render_lead(parts["lead"],parts["lead_side"])+render_section("Top Stories","The strongest stories in the current 30-day window.",parts["top_stories"],compact=True)+render_section("Education & Schools","Book bans, curriculum fights, DEI in schools, school boards, and parents’ rights campaigns.",parts["education"][:6])+render_section("Gender & Sexuality","Anti-trans panic, drag and pride backlash, pronoun fights, and gender-based outrage politics.",parts["gender"][:6])+render_section("Religion & Pluralism","Muslim school targeting, religious-liberty weaponization, and pluralism backlash.",parts["religion"][:6])+render_section("Race, DEI & Immigration","Anti-DEI backlash, white grievance rhetoric, and immigrant or refugee panic narratives.",parts["race"][:6])+render_section("Law & Order","Documented legal actions against Republican governments and Republican office holders, including court orders, injunctions, sanctions, indictments, convictions, and civil penalties.",parts["law_and_order"][:12],compact=True)+render_section("Not A Trans…","Arrests, charges, convictions, and sentencing stories involving explicitly conservative, MAGA, or religious figures in sex-crime cases. This section stays separate.",parts["not_a_trans"][:12],compact=True)+render_section("In the Wings","Borderline or adjacent stories from the last 30 days.",wings[:12],compact=True)
    return {"index.html":page_shell("Front Page","index.html",front_main,payload),"education.html":page_shell("Education & Schools","education.html",render_section("Education & Schools","Book bans, curriculum fights, DEI in schools, school boards, and parents’ rights campaigns.",parts["education"]),payload),"gender.html":page_shell("Gender & Sexuality","gender.html",render_section("Gender & Sexuality","Anti-trans panic, drag and pride backlash, pronoun fights, and gender-based outrage politics.",parts["gender"]),payload),"religion.html":page_shell("Religion & Pluralism","religion.html",render_section("Religion & Pluralism","Muslim school targeting, religious-liberty weaponization, and pluralism backlash.",parts["religion"]),payload),"race.html":page_shell("Race, DEI & Immigration","race.html",render_section("Race, DEI & Immigration","Anti-DEI backlash, white grievance rhetoric, and immigrant or refugee panic narratives.",parts["race"]),payload),"law-and-order.html":page_shell("Law & Order","law-and-order.html",render_section("Law & Order","Documented legal actions against Republican governments and Republican office holders, including court orders, injunctions, sanctions, indictments, convictions, and civil penalties.",parts["law_and_order"],compact=True),payload),"not-a-trans.html":page_shell("Not A Trans…","not-a-trans.html",render_section("Not A Trans…","Arrests, charges, convictions, and sentencing stories involving explicitly conservative, MAGA, or religious figures in sex-crime cases. This section stays separate and searches back to 2025-01-20.",parts["not_a_trans"],compact=True),payload),"wings.html":page_shell("In the Wings","wings.html",render_section("In the Wings","Borderline or adjacent stories from the last 30 days.",wings[:40],compact=True),payload)}
def write_pages(payload):
    for filename,content in build_page_html(payload).items(): (DOCS_DIR/filename).write_text(content, encoding="utf-8")
def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True); specs=load_feed_specs(); archive=load_json(ARCHIVE_FILE,{"seen":[],"reviews":[]}); seen=set(archive.get("seen",[])) if isinstance(archive,dict) else set(); reviews=archive.get("reviews",[]) if isinstance(archive,dict) else []
    if IGNORE_SEEN: seen=set()
    raw=[]
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures={ex.submit(fetch_candidates,spec): spec for spec in specs}
        for fut in as_completed(futures):
            spec=futures[fut]
            try:
                items=fut.result(); raw.extend(items); print(f'{spec["label"]}: {len(items)} candidates')
            except Exception as e:
                print(f'{spec["label"]}: ERROR {e}')
    raw.sort(key=lambda x:(x["prefilter"]["lexical_score"],x.get("published","")), reverse=True)
    candidates=[]; seen_local=set()
    for item in raw:
        key=article_key(item); title_key=re.sub(r"\W+"," ",item.get("title","").lower()).strip()
        if (not IGNORE_SEEN) and item.get("special_query") and key in seen: continue
        if (not IGNORE_SEEN) and (not item.get("special_query")) and (key in seen or title_key in seen): continue
        if key in seen_local or title_key in seen_local: continue
        seen_local.add(key); seen_local.add(title_key); candidates.append(item)
    candidates=candidates[:MAX_AI_REVIEWS_PER_RUN]
    reviewed=[]; current_kept=[]; current_wings=[]; current_rejected=[]; current_special=[]; current_law=[]
    with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
        futures={ex.submit(evaluate_article,item): item for item in candidates}
        for fut in as_completed(futures):
            item=futures[fut]; row={**item, **fut.result()}; reviewed.append(row); score=float(row.get("score",0)); bucket=row.get("bucket","reject")
            if bucket=="not_a_trans": current_special.append(row)
            elif bucket=="law_and_order": current_law.append(row)
            elif bucket=="keep" and score>=KEEP_MIN_SCORE: current_kept.append(row)
            elif bucket in {"keep","wings"} and score>=WINGS_MIN_SCORE:
                if bucket=="keep": row["bucket"]="wings"
                current_wings.append(row)
            else: current_rejected.append(row)
    for item in reviewed:
        seen.add(article_key(item)); seen.add(re.sub(r"\W+"," ",item.get("title","").lower()).strip())
    review_rows=[{"title":r.get("title"),"url":r.get("url"),"source":r.get("source"),"state":r.get("state"),"bucket":r.get("bucket"),"score":r.get("score"),"tags":r.get("tags",[]),"angle":r.get("angle"),"summary":r.get("summary"),"reason":r.get("reason"),"published":r.get("published")} for r in reviewed]
    reviews.extend(review_rows); reviews=reviews[-14000:]
    archived_kept=[r for r in reviews if r.get("bucket")=="keep" and is_within_days(r.get("published",""),ROLLING_DAYS)]
    archived_wings=[r for r in reviews if r.get("bucket")=="wings" and is_within_days(r.get("published",""),ROLLING_DAYS)]
    archived_special=[r for r in reviews if r.get("bucket")=="not_a_trans" and is_after_fixed_start(r.get("published",""),NOT_A_TRANS_START)]
    archived_law=[r for r in reviews if r.get("bucket")=="law_and_order" and is_within_days(r.get("published",""),ROLLING_DAYS)]
    merged_kept=sorted(dedupe_rows(current_kept+archived_kept), key=lambda x:(float(x.get("score",0)),x.get("published","")), reverse=True)
    merged_wings=sorted(dedupe_rows(current_wings+archived_wings), key=lambda x:(float(x.get("score",0)),x.get("published","")), reverse=True)
    merged_special=sorted(dedupe_rows(current_special+archived_special), key=lambda x:(float(x.get("score",0)),x.get("published","")), reverse=True)
    merged_law=sorted(dedupe_rows(current_law+archived_law), key=lambda x:(float(x.get("score",0)),x.get("published","")), reverse=True)
    payload={"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"counts":{"kept":len(merged_kept),"wings":len(merged_wings),"law_and_order":len(merged_law),"not_a_trans":len(merged_special),"rejected":len(current_rejected),"reviewed":len(reviewed),"new_kept_this_run":len(current_kept),"new_wings_this_run":len(current_wings),"new_law_and_order_this_run":len(current_law),"new_not_a_trans_this_run":len(current_special),"rolling_days":ROLLING_DAYS,"not_a_trans_start":NOT_A_TRANS_START},"kept":merged_kept,"in_the_wings":merged_wings,"law_and_order":merged_law,"not_a_trans":merged_special,"rejected":sorted(current_rejected, key=lambda x:x.get("score",0), reverse=True)[:200]}
    save_json(ARCHIVE_FILE,{"seen":sorted(seen),"reviews":reviews}); save_json(OUTPUT_FILE,payload); write_pages(payload)
    print(f"Reviewed this run: {len(reviewed)}"); print(f"Published windows: kept={len(merged_kept)} wings={len(merged_wings)} law_and_order={len(merged_law)} not_a_trans={len(merged_special)}")
    for filename,_ in SECTION_PAGES: print(f"Saved {DOCS_DIR/filename}")
    print(f"Saved {OUTPUT_FILE}")
if __name__=="__main__": main()

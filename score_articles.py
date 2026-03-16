#!/usr/bin/env python3
import json
import os
import re
from typing import Any, Dict, List

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

SYSTEM_PROMPT = """
You classify U.S. news stories for a satire/news-curation site tracking conservative culture-war panic,
identity grievance, and symbolic social outrage.

Return one of three buckets:
- "keep" = clearly on-theme
- "wings" = politically adjacent / borderline / maybe useful later
- "reject" = not relevant, or crime/violence/scandal-first

HARD THEME REQUIREMENT
A story can only be "keep" if a central conflict involves identity, pluralism, or inclusion in the U.S.,
especially around race, religion, immigration, gender, sexuality, DEI, or "traditional Christian/white/straight values."

KEEP stories about:
- anti-DEI, anti-diversity, anti-equity, anti-inclusion backlash
- anti-trans outrage, pronoun fights, bathroom fights, sports participation panic
- drag, Pride, LGBTQ inclusion backlash
- school board, curriculum, library, teacher, and book-ban controversies tied to identity/inclusion
- anti-immigrant cultural panic framed around identity, values, or "real America"
- anti-Muslim, anti-non-Christian, or selective "religious liberty" grievance politics
- white grievance rhetoric, "young white men", "young white male man", "protect white people", "Western civilization", "traditional values"
- lawmakers, activists, churches, or influencers targeting institutions over identity topics
- anti-Muslim school-voucher or school-funding stories targeting Islamic schools

WINGS stories:
- politically adjacent culture-war stories with weak identity signals
- vague school/religion/"parents' rights" stories that may be relevant but are not clearly identity-centered
- conservative grievance stories where the title/summary is too thin to confirm strong thematic fit
- broader political stories connected to your themes but not explicit enough for KEEP

REJECT stories about:
- murders, shootings, bombings, assaults, threats, terrorism, or other violence-first events
- sexual assault, molestation, trafficking, exploitation, or abuse cases
- generic crime/court stories even if identity terms appear
- election fraud, fake electors, corruption, indictments, bribery, campaign finance, prosecutions
- generic partisan or legislative news with no central identity/pluralism target
- horse-race politics
- celebrity or entertainment stories without a real culture-war grievance frame

IMPORTANT DISTINCTION
Keep "conservatives angry about trans inclusion."
Reject "trans person accused of a crime."
Keep "officials target Muslim school funding."
Keep "Republicans target Islamic schools in voucher/funding fights."
Reject "Michigan fake electors story" unless the real center is identity politics, which it usually is not.

Return JSON only with:
{
  "bucket": "keep" or "wings" or "reject",
  "score": number from 0 to 10,
  "tags": ["tag1", "tag2"],
  "angle": "short phrase describing the narrative",
  "summary": "1-2 sentence neutral summary",
  "reason": "brief reason for the bucket"
}
"""

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

TAG_RULES = [
    ("anti-dei", ["dei", "diversity", "equity", "inclusion", "affirmative action"]),
    ("anti-trans", ["trans", "transgender", "pronoun", "bathroom bill", "gender ideology"]),
    ("book-bans", ["book ban", "banned books", "library"]),
    ("schools", ["school board", "curriculum", "teacher", "classroom", "voucher", "school choice"]),
    ("religion", ["religious liberty", "christian values", "muslim", "mosque", "islamic school", "muslim school", "faith-based", "sharia", "cair"]),
    ("immigration", ["immigrant", "immigration", "refugee", "illegal alien"]),
    ("white-grievance", ["white people", "white boys", "young white men", "young white male", "white male man", "western civilization", "traditional values", "disenfranchise"]),
    ("lgbtq-panic", ["drag", "pride", "lgbt", "lgbtq", "nonbinary"]),
    ("parents-rights", ["parents' rights", "parents rights"]),
]

def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model response")
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("No valid JSON found")

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")

def _build_tags(blob: str) -> List[str]:
    out: List[str] = []
    for tag, needles in TAG_RULES:
        if any(n in blob for n in needles):
            out.append(tag)
    return out[:6]

def _heuristic_review(article: Dict[str, Any]) -> Dict[str, Any]:
    blob = " ".join([
        article.get("title", ""),
        article.get("summary", ""),
        article.get("source", ""),
        json.dumps(article.get("prefilter", {}), ensure_ascii=False),
    ]).lower()

    identity_hits = [t for t in IDENTITY_TERMS if t in blob]
    outrage_hits = [t for t in OUTRAGE_TERMS if t in blob]
    actor_hits = [t for t in RIGHT_ACTOR_TERMS if t in blob]
    crime_hits = [t for t in CRIME_VIOLENCE_TERMS if t in blob]
    scandal_hits = [t for t in GENERIC_SCANDAL_TERMS if t in blob]

    tags = _build_tags(blob)
    if not tags:
        tags = article.get("prefilter", {}).get("include_hits", [])[:4]

    score = (
        min(len(identity_hits), 5) * 1.8
        + min(len(outrage_hits), 4) * 1.0
        + min(len(actor_hits), 3) * 0.9
        - min(len(crime_hits), 4) * 2.5
        - min(len(scandal_hits), 3) * 2.6
    )
    score = round(max(0.0, min(10.0, score)), 1)

    strong_identity = len(identity_hits) >= 2 or (len(identity_hits) >= 1 and len(tags) >= 1)
    scandal_first = len(scandal_hits) >= 1 and len(identity_hits) == 0
    crime_first = len(crime_hits) >= 2

    if crime_first or scandal_first:
        bucket = "reject"
    elif strong_identity and (len(outrage_hits) >= 1 or len(actor_hits) >= 1 or score >= 4.6):
        bucket = "keep"
    elif len(identity_hits) >= 1:
        bucket = "wings"
    elif len(actor_hits) >= 1 and len(outrage_hits) >= 1:
        bucket = "wings"
    else:
        bucket = "reject"

    if bucket == "keep" and len(identity_hits) == 0:
        bucket = "wings"

    if bucket == "keep":
        reason = "Clear identity/pluralism-targeted outrage story."
    elif bucket == "wings":
        reason = "Borderline or adjacent to theme; useful for later review."
    else:
        reason = "Generic scandal/crime/politics story or lacks central identity target."

    angle = "borderline political grievance story"
    if "anti-trans" in tags:
        angle = "anti-trans moral panic"
    elif "anti-dei" in tags:
        angle = "DEI backlash"
    elif "religion" in tags:
        angle = "religion / pluralism backlash"
    elif "immigration" in tags:
        angle = "immigrant identity panic"
    elif "white-grievance" in tags:
        angle = "white grievance rhetoric"
    elif "parents-rights" in tags:
        angle = "parents' rights culture-war push"

    return {
        "bucket": bucket,
        "score": score,
        "tags": tags,
        "angle": angle,
        "summary": article.get("summary", "")[:600],
        "reason": reason,
    }

def _clean_review(review: Dict[str, Any], article: Dict[str, Any]) -> Dict[str, Any]:
    tags = []
    for x in review.get("tags", []):
        s = _slug(str(x))
        if s and s not in tags:
            tags.append(s)

    bucket = str(review.get("bucket", "reject")).strip().lower()
    if bucket not in {"keep", "wings", "reject"}:
        bucket = "reject"

    return {
        "bucket": bucket,
        "score": round(float(review.get("score", 0)), 1),
        "tags": tags[:6],
        "angle": str(review.get("angle", "")).strip()[:180],
        "summary": str(review.get("summary", "")).strip()[:600] or article.get("summary", "")[:600],
        "reason": str(review.get("reason", "")).strip()[:300],
    }

def evaluate_article(article: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if OpenAI is None or not api_key:
        return _clean_review(_heuristic_review(article), article)

    try:
        client = OpenAI(api_key=api_key)
        user_payload = {
            "title": article.get("title"),
            "url": article.get("url"),
            "source": article.get("source"),
            "state": article.get("state"),
            "published": article.get("published"),
            "summary": article.get("summary"),
            "prefilter": article.get("prefilter", {}),
        }
        response = client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        )
        parsed = _extract_json(getattr(response, "output_text", "") or "")
        cleaned = _clean_review(parsed, article)

        blob = f"{article.get('title','')} {article.get('summary','')}".lower()
        has_identity = any(t in blob for t in IDENTITY_TERMS)
        if cleaned["bucket"] == "keep" and not has_identity:
            cleaned["bucket"] = "wings"
            cleaned["reason"] = "Downgraded from keep because no clear identity/pluralism target was visible."
        if any(t in blob for t in GENERIC_SCANDAL_TERMS) and not has_identity:
            cleaned["bucket"] = "reject"
            cleaned["reason"] = "Rejected as generic scandal/electors/corruption news rather than identity politics."
        return cleaned
    except Exception as e:
        fallback = _heuristic_review(article)
        fallback["reason"] = f"Heuristic fallback used. {type(e).__name__}: {e}"
        return _clean_review(fallback, article)

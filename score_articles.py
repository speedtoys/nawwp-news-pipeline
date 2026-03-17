#!/usr/bin/env python3
import json
import os
import re

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

IDENTITY = [
    "dei", "diversity", "equity", "inclusion", "anti-woke", "woke", "trans", "transgender",
    "pronoun", "drag", "pride", "lgbt", "lgbtq", "book ban", "banned books", "library",
    "school board", "parents' rights", "voucher", "school choice", "religious liberty",
    "christian values", "traditional values", "western civilization", "white people",
    "white boys", "young white men", "muslim", "islamic", "muslim school", "islamic school",
    "immigrant", "immigration", "cair", "sharia"
]

OUTRAGE = [
    "backlash", "outrage", "criticized", "criticizes", "slams", "targets", "opposes", "ban",
    "bans", "blocks", "defund", "exclude", "excluded", "remove", "pull funding", "lawsuit",
    "sues", "debate", "hearing", "boycott", "pressure campaign"
]

ACTORS = [
    "maga", "trump", "republican", "republicans", "gop", "conservative", "conservatives",
    "fox news", "moms for liberty", "charlie kirk", "erika kirk", "governor",
    "attorney general", "state lawmakers", "christian nationalist"
]

CRIME = [
    "shooting", "shot", "shot up", "gunman", "gunfire", "opened fire",
    "murder", "murdered", "killed", "dead", "injured", "wounded",
    "bombing", "terror", "terrorist", "arrested", "charged with",
    "indicted", "convicted", "sentenced", "assault", "attacked", "attack",
    "rape", "sexual assault", "trafficking", "abuse", "homicide",
    "stabbing", "stabbed"
]

SCANDAL = [
    "fake electors", "alternate electors", "electors", "election fraud", "campaign finance",
    "bribery", "corruption", "indictment", "prosecution", "felony", "embezzlement"
]

ANGLE_RULES = [
    ("anti-trans panic", ["trans", "transgender", "gender ideology", "pronoun"]),
    ("anti-dei backlash", ["dei", "diversity", "equity", "inclusion"]),
    ("anti-muslim backlash", ["muslim", "islamic school", "muslim school", "sharia", "cair"]),
    ("white grievance rhetoric", ["young white men", "white people", "white boys", "western civilization"]),
    ("book bans and curriculum", ["book ban", "banned books", "library", "curriculum"]),
    ("parents' rights push", ["parents' rights", "parents rights"]),
    ("anti-immigrant panic", ["immigrant", "immigration", "refugee", "illegal alien"]),
    ("religious-liberty grievance", ["religious liberty", "christian values", "traditional values"]),
]

TAG_RULES = [
    ("anti-dei", ["dei", "diversity", "equity", "inclusion"]),
    ("anti-trans", ["trans", "transgender", "gender ideology", "pronoun"]),
    ("anti-muslim", ["muslim", "islamic", "islamic school", "muslim school", "sharia", "cair"]),
    ("white-grievance", ["white people", "white boys", "young white men", "western civilization"]),
    ("book-bans", ["book ban", "banned books", "library"]),
    ("parents-rights", ["parents' rights", "parents rights"]),
    ("immigration", ["immigrant", "immigration", "refugee", "illegal alien"]),
    ("religious-liberty", ["religious liberty", "christian values", "traditional values"]),
    ("lgbtq-panic", ["drag", "pride", "lgbt", "lgbtq"]),
]

PROMPT = (
    "Classify a U.S. news story as keep, wings, or reject. "
    "Keep only identity/pluralism backlash stories. "
    "Reject generic crime, violent incidents, scandal, corruption, electors, and generic politics. "
    "If the story is centered on an actual crime or violent act, reject it even if it includes identity terms. "
    "Return JSON with bucket, score, tags, angle, summary, reason."
)


def build_tags(blob: str) -> list[str]:
    out = []
    for tag, needles in TAG_RULES:
        if any(n in blob for n in needles):
            out.append(tag)
    return out[:6]


def build_angle(blob: str) -> str:
    for angle, needles in ANGLE_RULES:
        if any(n in blob for n in needles):
            return angle
    return "identity-outrage story"


def heuristic(article: dict) -> dict:
    blob = " ".join([
        article.get("title", ""),
        article.get("summary", ""),
        article.get("source", "")
    ]).lower()

    i = [x for x in IDENTITY if x in blob]
    o = [x for x in OUTRAGE if x in blob]
    a = [x for x in ACTORS if x in blob]
    c = [x for x in CRIME if x in blob]
    s = [x for x in SCANDAL if x in blob]

    score = max(
        0.0,
        min(
            10.0,
            round(len(i) * 1.8 + len(o) * 1.0 + len(a) * 0.8 - len(c) * 2.5 - len(s) * 2.6, 1)
        ),
    )

    violent_crime_override = any(x in blob for x in [
        "shot", "shot up", "shooting", "gunman", "gunfire", "opened fire",
        "killed", "murder", "murdered", "dead", "injured", "wounded",
        "assault", "attack", "attacked", "stabbing", "stabbed"
    ])

    if violent_crime_override:
        bucket = "reject"
    elif len(c) >= 1:
        bucket = "reject"
    elif s and not i:
        bucket = "reject"
    elif i and (o or a or score >= 4.5):
        bucket = "keep"
    elif i or (a and o):
        bucket = "wings"
    else:
        bucket = "reject"

    return {
        "bucket": bucket,
        "score": score,
        "tags": build_tags(blob),
        "angle": build_angle(blob),
        "summary": article.get("summary", "")[:500],
        "reason": {
            "keep": "On-theme identity/pluralism backlash story.",
            "wings": "Borderline but worth a second look.",
            "reject": "Generic scandal, real-world crime, violence, or off-theme politics."
        }[bucket]
    }


def evaluate_article(article: dict) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if OpenAI is None or not api_key:
        return heuristic(article)

    try:
        client = OpenAI(api_key=api_key)
        payload = {
            "title": article.get("title"),
            "summary": article.get("summary"),
            "source": article.get("source"),
            "state": article.get("state"),
        }

        resp = client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )

        text = getattr(resp, "output_text", "") or ""
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)

        if not match:
            return heuristic(article)

        out = json.loads(match.group(0))

        if out.get("bucket") not in {"keep", "wings", "reject"}:
            return heuristic(article)

        blob = (article.get("title", "") + " " + article.get("summary", "")).lower()
        out["tags"] = out.get("tags") or build_tags(blob)
        out["angle"] = out.get("angle") or build_angle(blob)
        out["summary"] = out.get("summary") or article.get("summary", "")[:500]
        out["reason"] = out.get("reason") or heuristic(article)["reason"]

        return out

    except Exception:
        return heuristic(article)

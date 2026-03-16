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

def heuristic(article):
    blob = " ".join([article.get("title",""), article.get("summary",""), article.get("source","")]).lower()
    i = [x for x in IDENTITY if x in blob]
    o = [x for x in OUTRAGE if x in blob]
    a = [x for x in ACTORS if x in blob]
    c = [x for x in CRIME if x in blob]
    s = [x for x in SCANDAL if x in blob]
    score = max(0.0, min(10.0, round(len(i)*1.8 + len(o)*1.0 + len(a)*0.8 - len(c)*2.5 - len(s)*2.6, 1)))

    if len(c) >= 2 or (s and not i):
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
        "tags": i[:5],
        "angle": "identity-outrage story" if bucket != "reject" else "off-theme",
        "summary": article.get("summary","")[:500],
        "reason": "heuristic classification"
    }

def evaluate_article(article):
    api_key = os.getenv("OPENAI_API_KEY","").strip()
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
        prompt = (
            "Classify this U.S. news story as keep, wings, or reject. "
            "Keep only if it is centered on identity/pluralism backlash around race, religion, immigration, gender, sexuality, or DEI. "
            "Reject crime, violence, corruption, fake electors, generic scandal, or generic politics. "
            "Return JSON with bucket, score, tags, angle, summary, reason.\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        resp = client.responses.create(model=MODEL, input=prompt)
        text = getattr(resp, "output_text", "") or ""
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return heuristic(article)
        out = json.loads(m.group(0))
        if out.get("bucket") not in {"keep","wings","reject"}:
            return heuristic(article)
        return out
    except Exception:
        return heuristic(article)


#!/usr/bin/env python3
import json, os, re
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
IDENTITY = ["dei","diversity","equity","inclusion","anti-woke","woke","transgender","gender ideology","pronoun","trans rights","trans student","trans athlete","drag","pride","lgbt","lgbtq","book ban","banned books","library","school board","parents' rights","parents rights","voucher","school choice","religious liberty","christian values","traditional values","western civilization","white people","white boys","young white men","muslim","islamic","muslim school","islamic school","immigrant","immigration","refugee","illegal alien","cair","sharia"]
OUTRAGE = ["backlash","outrage","criticized","criticizes","slams","targets","opposes","ban","bans","blocks","defund","exclude","excluded","remove","pull funding","lawsuit","sues","debate","hearing","boycott","pressure campaign"]
ACTORS = ["maga","trump","republican","republicans","gop","conservative","conservatives","fox news","moms for liberty","charlie kirk","erika kirk","governor","attorney general","state lawmakers","christian nationalist"]
GENERAL_CRIME = ["shooting","shot","shot up","gunman","gunfire","opened fire","murder","murdered","killed","dead","injured","wounded","bombing","terror","terrorist","arrested","charged with","indicted","convicted","sentenced","assault","attacked","attack","rape","sexual assault","trafficking","abuse","homicide","stabbing","stabbed"]
SEX_CRIME = ["rape","sexual assault","sex abuse","sexual abuse","child sexual abuse","molestation","molested","child pornography","csam","exploitation","grooming","solicitation","sentenced","convicted","arrested","charged with","guilty plea","pleaded guilty"]
HYPOCRISY_ACTORS = ["republican","gop","maga","conservative","pastor","priest","church","church leader","youth pastor","minister","deacon","christian school","family values","parents' rights","anti-lgbt","anti-trans","religious leader"]
SCANDAL = ["fake electors","alternate electors","electors","election fraud","campaign finance","bribery","corruption","indictment","prosecution","felony","embezzlement"]
ANGLE_RULES = [("anti-trans panic", ["transgender","gender ideology","pronoun","trans rights","trans student","trans athlete"]),("anti-dei backlash", ["dei","diversity","equity","inclusion"]),("anti-muslim backlash", ["muslim","islamic school","muslim school","sharia","cair"]),("white grievance rhetoric", ["young white men","white people","white boys","western civilization"]),("book bans and curriculum", ["book ban","banned books","library","curriculum"]),("parents' rights push", ["parents' rights","parents rights"]),("anti-immigrant panic", ["immigrant","immigration","refugee","illegal alien"]),("religious-liberty grievance", ["religious liberty","christian values","traditional values"])]
TAG_RULES = [("anti-dei", ["dei","diversity","equity","inclusion"]),("anti-trans", ["transgender","gender ideology","pronoun","trans rights","trans student","trans athlete"]),("anti-muslim", ["muslim","islamic","islamic school","muslim school","sharia","cair"]),("white-grievance", ["white people","white boys","young white men","western civilization"]),("book-bans", ["book ban","banned books","library"]),("parents-rights", ["parents' rights","parents rights"]),("immigration", ["immigrant","immigration","refugee","illegal alien"]),("religious-liberty", ["religious liberty","christian values","traditional values"]),("lgbtq-panic", ["drag","pride","lgbt","lgbtq"]),("not-a-trans", ["republican","gop","maga","conservative","pastor","priest","church","youth pastor","christian school"])]
PROMPT = "Classify a U.S. news story as keep, wings, reject, or not_a_trans. Use not_a_trans only for sex-crime legal stories explicitly involving conservative, Republican, MAGA, church, pastor, priest, Christian school, family-values, anti-LGBT, or anti-trans figures. Reject generic crime, violent incidents, scandal, corruption, electors, and generic politics. Return JSON with bucket, score, tags, angle, summary, reason."

def term_matches(term: str, blob: str) -> bool:
    term = term.lower().strip(); blob = blob.lower()
    if " " in term or "-" in term or "'" in term:
        return term in blob
    return re.search(rf"\b{re.escape(term)}\b", blob) is not None

def collect_matches(terms, blob): return [term for term in terms if term_matches(term, blob)]

def build_tags(blob: str):
    out = []
    for tag, needles in TAG_RULES:
        if any(term_matches(n, blob) for n in needles):
            out.append(tag)
    return out[:6]

def build_angle(blob: str):
    if any(term_matches(n, blob) for n in HYPOCRISY_ACTORS) and any(term_matches(n, blob) for n in SEX_CRIME):
        return "not a trans..."
    for angle, needles in ANGLE_RULES:
        if any(term_matches(n, blob) for n in needles):
            return angle
    return "identity-outrage story"

def heuristic(article: dict):
    blob = " ".join([article.get("title",""), article.get("summary",""), article.get("source","")]).lower()
    i = collect_matches(IDENTITY, blob); o = collect_matches(OUTRAGE, blob); a = collect_matches(ACTORS, blob)
    gc = collect_matches(GENERAL_CRIME, blob); sx = collect_matches(SEX_CRIME, blob); hx = collect_matches(HYPOCRISY_ACTORS, blob); s = collect_matches(SCANDAL, blob)
    special = bool(sx and hx)
    score = max(0.0, min(10.0, round(len(i)*1.8 + len(o)*1.0 + len(a)*0.8 + len(hx)*1.2 + len(sx)*0.7 - len(s)*2.6, 1)))
    violent_non_special = any(term_matches(x, blob) for x in ["shot","shot up","shooting","gunman","gunfire","opened fire","killed","murder","murdered","dead","injured","wounded","stabbing","stabbed","bombing"])
    if special:
        bucket, reason = "not_a_trans", "Sex-crime article involving an explicitly conservative, MAGA, or religious figure."
    elif violent_non_special:
        bucket, reason = "reject", "Generic violent crime or incident."
    elif gc and not i:
        bucket, reason = "reject", "Generic crime or legal story outside the site's main scope."
    elif s and not i:
        bucket, reason = "reject", "Generic scandal or corruption story."
    elif i and (o or a or score >= 4.5):
        bucket, reason = "keep", "On-theme identity/pluralism backlash story."
    elif i or (a and o):
        bucket, reason = "wings", "Borderline but worth a second look."
    else:
        bucket, reason = "reject", "Off-theme politics or generic news."
    return {"bucket": bucket, "score": score, "tags": build_tags(blob), "angle": build_angle(blob), "summary": article.get("summary","")[:500], "reason": reason}

def evaluate_article(article: dict):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if OpenAI is None or not api_key:
        return heuristic(article)
    try:
        client = OpenAI(api_key=api_key)
        payload = {"title": article.get("title"), "summary": article.get("summary"), "source": article.get("source"), "state": article.get("state")}
        resp = client.responses.create(model=MODEL, input=[{"role":"system","content":PROMPT},{"role":"user","content":json.dumps(payload, ensure_ascii=False)}])
        text = getattr(resp, "output_text", "") or ""
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return heuristic(article)
        out = json.loads(match.group(0))
        if out.get("bucket") not in {"keep","wings","reject","not_a_trans"}:
            return heuristic(article)
        blob = (article.get("title","") + " " + article.get("summary","")).lower()
        if collect_matches(SEX_CRIME, blob) and collect_matches(HYPOCRISY_ACTORS, blob):
            out["bucket"] = "not_a_trans"
            out["reason"] = "Sex-crime article involving an explicitly conservative, MAGA, or religious figure."
        out["tags"] = out.get("tags") or build_tags(blob)
        out["angle"] = out.get("angle") or build_angle(blob)
        out["summary"] = out.get("summary") or article.get("summary","")[:500]
        out["reason"] = out.get("reason") or heuristic(article)["reason"]
        return out
    except Exception:
        return heuristic(article)

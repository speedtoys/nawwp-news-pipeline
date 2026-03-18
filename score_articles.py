
#!/usr/bin/env python3
import json, os, re
try:
    from openai import OpenAI
except Exception:
    OpenAI = None
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
IDENTITY = ["dei","diversity","equity","inclusion","anti-woke","woke","transgender","gender ideology","pronoun","trans rights","trans student","trans athlete","drag","pride","lgbt","lgbtq","book ban","banned books","library","school board","parents' rights","parents rights","voucher","school choice","religious liberty","christian values","traditional values","western civilization","white people","white boys","young white men","muslim","islamic","muslim school","islamic school","immigrant","immigration","refugee","illegal alien","cair","sharia"]
OUTRAGE = ["backlash","outrage","criticized","criticizes","slams","targets","opposes","ban","bans","blocks","defund","exclude","excluded","remove","pull funding","lawsuit","sues","debate","hearing","boycott","pressure campaign"]
ACTORS = ["maga","trump","republican","republicans","gop","conservative","conservatives","governor","attorney general","state lawmakers"]
GENERAL_CRIME = ["shooting","shot","shot up","gunman","gunfire","opened fire","murder","murdered","killed","dead","injured","wounded","bombing","terror","terrorist","arrested","charged with","indicted","convicted","sentenced","assault","attacked","attack","rape","sexual assault","trafficking","abuse","homicide","stabbing","stabbed"]
SEX_CRIME = ["rape","sexual assault","sex abuse","sexual abuse","child sexual abuse","molestation","molested","child pornography","csam","exploitation","grooming","solicitation","sentenced","convicted","arrested","charged with","guilty plea","pleaded guilty"]
HYPOCRISY_ACTORS = ["republican","gop","maga","conservative","pastor","priest","church","church leader","youth pastor","minister","deacon","christian school","family values","parents' rights","anti-lgbt","anti-trans","religious leader"]
LAW_ORDER_ACTORS = ["trump administration","federal agency","republican governor","republican attorney general","republican legislature","republican sheriff","republican county","republican school board","republican mayor","republican official","gop official","republican legislator","republican officeholder","trump adviser","trump official","republican county clerk","attorney general","governor","sheriff","mayor","county clerk","school board"]
LAW_ORDER_EVENTS = ["court order","injunction","ruling","judge ordered","unconstitutional","unlawful","illegal","contempt","settlement","civil penalty","civil penalties","consent decree","damages","sanctions","sanctioned","blocked by court","ethics violation","ethics finding","indicted","charged","convicted","sentenced","pleaded guilty","guilty plea"]
SCANDAL = ["fake electors","alternate electors","electors","election fraud","campaign finance","bribery","corruption","indictment","prosecution","felony","embezzlement"]

def term_matches(term, blob):
    term = term.lower().strip(); blob = blob.lower()
    if " " in term or "-" in term or "'" in term: return term in blob
    return re.search(rf"\b{re.escape(term)}\b", blob) is not None

def collect_matches(terms, blob): return [t for t in terms if term_matches(t, blob)]

def heuristic(article):
    blob = " ".join([article.get("title",""), article.get("summary",""), article.get("source","")]).lower()
    i,o,a = collect_matches(IDENTITY,blob), collect_matches(OUTRAGE,blob), collect_matches(ACTORS,blob)
    gc,sx,hx = collect_matches(GENERAL_CRIME,blob), collect_matches(SEX_CRIME,blob), collect_matches(HYPOCRISY_ACTORS,blob)
    lx,le,s = collect_matches(LAW_ORDER_ACTORS,blob), collect_matches(LAW_ORDER_EVENTS,blob), collect_matches(SCANDAL,blob)
    special = bool(sx and hx); law = bool(lx and le)
    score = max(0.0, min(10.0, round(len(i)*1.8 + len(o)*1.0 + len(a)*0.8 + len(hx)*1.2 + len(lx)*1.0 + len(le)*1.0 - len(s)*2.6, 1)))
    violent_non_special = any(term_matches(x, blob) for x in ["shot","shot up","shooting","gunman","gunfire","opened fire","killed","murder","murdered","dead","injured","wounded","stabbing","stabbed","bombing"])
    if special:
        bucket, reason, angle = "not_a_trans", "Sex-crime article involving an explicitly conservative, MAGA, or religious figure.", "not a trans..."
    elif law:
        bucket, reason, angle = "law_and_order", "Documented legal action against a Republican government body or Republican office holder.", "law & order"
    elif violent_non_special or (gc and not i):
        bucket, reason, angle = "reject", "Generic crime or violent legal story outside the site's main scope.", "off-theme"
    elif s and not i:
        bucket, reason, angle = "reject", "Generic scandal or corruption story.", "off-theme"
    elif i and (o or a or score >= 4.5):
        bucket, reason, angle = "keep", "On-theme identity/pluralism backlash story.", "identity-outrage story"
    elif i or (a and o):
        bucket, reason, angle = "wings", "Borderline but worth a second look.", "identity-outrage story"
    else:
        bucket, reason, angle = "reject", "Off-theme politics or generic news.", "off-theme"
    tags = []
    if law: tags.append("law-and-order")
    if special: tags.append("not-a-trans")
    return {"bucket": bucket, "score": score, "tags": tags[:4], "angle": angle, "summary": article.get("summary","")[:500], "reason": reason}

def evaluate_article(article):
    return heuristic(article)

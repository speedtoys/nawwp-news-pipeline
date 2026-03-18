
#!/usr/bin/env python3
import re

IDENTITY = ["dei","diversity","equity","inclusion","anti-woke","woke","transgender","gender ideology","pronoun","trans rights","trans student","trans athlete","drag","pride","lgbt","lgbtq","book ban","banned books","library","school board","parents' rights","parents rights","voucher","school choice","religious liberty","christian values","traditional values","western civilization","white people","white boys","young white men","muslim","islamic","muslim school","islamic school","immigrant","immigration","refugee","illegal alien","cair","sharia"]
OUTRAGE = ["backlash","outrage","criticized","criticizes","slams","targets","opposes","ban","bans","blocks","defund","exclude","excluded","remove","pull funding","lawsuit","sues","debate","hearing","boycott","pressure campaign"]
ACTORS = ["maga","trump","republican","republicans","gop","conservative","conservatives","governor","attorney general","state lawmakers"]
GENERAL_CRIME = ["shooting","shot","shot up","gunman","gunfire","opened fire","murder","murdered","killed","dead","injured","wounded","bombing","terror","terrorist","arrested","charged with","indicted","convicted","sentenced","assault","attacked","attack","rape","sexual assault","trafficking","abuse","homicide","stabbing","stabbed"]
SEX_CRIME = ["rape","sexual assault","sex abuse","sexual abuse","child sexual abuse","molestation","molested","child pornography","csam","exploitation","grooming","solicitation","sentenced","convicted","arrested","charged with","guilty plea","pleaded guilty"]
HYPOCRISY_ACTORS = ["republican","gop","maga","conservative","pastor","priest","church","church leader","youth pastor","minister","deacon","christian school","family values","parents' rights","anti-lgbt","anti-trans","religious leader"]
LAW_ORDER_ACTORS = ["trump administration","federal agency","administration official","dhs","ice","doj","hhs","education department","epa","republican governor","republican attorney general","republican legislature","republican sheriff","republican county","republican school board","republican mayor","republican official","gop official","republican legislator","republican officeholder","trump adviser","trump official","republican county clerk","attorney general","governor","sheriff","mayor","county clerk","school board","election board","secretary of state","elections office"]
LAW_ORDER_EVENTS = ["court order","injunction","ruling","judge ordered","blocked by court","federal judge","ordered release","ordered to comply","unconstitutional","unlawful","illegal","contempt","settlement","civil penalty","civil penalties","consent decree","damages","sanctions","sanctioned","ethics violation","ethics finding","indicted","charged","convicted","sentenced","pleaded guilty","guilty plea","due process","habeas","records law","voting rights","map ruled"]
SCANDAL = ["fake electors","alternate electors","electors","election fraud","campaign finance","bribery","corruption","indictment","prosecution","felony","embezzlement"]

def term_matches(term, blob):
    term = term.lower().strip(); blob = blob.lower()
    if " " in term or "-" in term or "'" in term:
        return term in blob
    return re.search(rf"\b{re.escape(term)}\b", blob) is not None

def collect_matches(terms, blob):
    return [t for t in terms if term_matches(t, blob)]

def evaluate_article(article):
    blob = " ".join([article.get("title",""), article.get("summary",""), article.get("source","")]).lower()
    i,o,a = collect_matches(IDENTITY,blob), collect_matches(OUTRAGE,blob), collect_matches(ACTORS,blob)
    gc,sx,hx = collect_matches(GENERAL_CRIME,blob), collect_matches(SEX_CRIME,blob), collect_matches(HYPOCRISY_ACTORS,blob)
    lx,le,s = collect_matches(LAW_ORDER_ACTORS,blob), collect_matches(LAW_ORDER_EVENTS,blob), collect_matches(SCANDAL,blob)
    special = bool(sx and hx)
    law = (len(lx) >= 1 and len(le) >= 1) or (("ice" in blob or "dhs" in blob or "federal agency" in blob or "trump administration" in blob) and len(le) >= 1)
    score = max(0.0, min(10.0, round(len(i)*1.8 + len(o)*1.0 + len(a)*0.8 + len(hx)*1.2 + len(lx)*1.0 + len(le)*1.0 - len(s)*2.2, 1)))
    violent_non_special = any(term_matches(x, blob) for x in ["shot","shot up","shooting","gunman","gunfire","opened fire","killed","murder","murdered","dead","injured","wounded","stabbing","stabbed","bombing"])
    if special:
        return {"bucket":"not_a_trans","score":score,"tags":["not-a-trans"],"angle":"not a trans...","summary":article.get("summary","")[:500],"reason":"Sex-crime article involving an explicitly conservative, MAGA, or religious figure."}
    if law:
        return {"bucket":"law_and_order","score":score,"tags":["law-and-order"],"angle":"law & order","summary":article.get("summary","")[:500],"reason":"Documented legal action against a Republican government body, federal agency, or Republican office holder."}
    if violent_non_special or (gc and not i):
        return {"bucket":"reject","score":score,"tags":[],"angle":"off-theme","summary":article.get("summary","")[:500],"reason":"Generic crime or violent legal story outside the site's main scope."}
    if s and not i:
        return {"bucket":"reject","score":score,"tags":[],"angle":"off-theme","summary":article.get("summary","")[:500],"reason":"Generic scandal or corruption story."}
    if i and (o or a or score >= 4.5):
        return {"bucket":"keep","score":score,"tags":[],"angle":"identity-outrage story","summary":article.get("summary","")[:500],"reason":"On-theme identity/pluralism backlash story."}
    if i or (a and o):
        return {"bucket":"wings","score":score,"tags":[],"angle":"identity-outrage story","summary":article.get("summary","")[:500],"reason":"Borderline but worth a second look."}
    return {"bucket":"reject","score":score,"tags":[],"angle":"off-theme","summary":article.get("summary","")[:500],"reason":"Off-theme politics or generic news."}

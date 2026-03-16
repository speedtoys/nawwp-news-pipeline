import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
MODEL = (os.getenv("OPENAI_MODEL") or "gpt-5-mini").strip()

client = OpenAI(api_key=OPENAI_API_KEY)

ALLOWED_TOPICS = [
    {"topic": "Education", "section_slug": "education"},
    {"topic": "Religion / Church-State", "section_slug": "religion-church-state"},
    {"topic": "Immigration / Identity", "section_slug": "immigration-identity"},
    {"topic": "Books / Libraries / Curriculum", "section_slug": "books-libraries-curriculum"},
    {"topic": "Gender / LGBTQ", "section_slug": "gender-lgbtq"},
    {"topic": "DEI / Diversity Backlash", "section_slug": "dei-diversity-backlash"},
    {"topic": "Voting / Civic Panic", "section_slug": "voting-civic-panic"},
    {"topic": "General Culture War", "section_slug": "general-culture-war"},
]

TOPIC_BY_NAME = {item["topic"].lower(): item for item in ALLOWED_TOPICS}
TOPIC_BY_SLUG = {item["section_slug"]: item for item in ALLOWED_TOPICS}

SYSTEM_PROMPT = """
You are reviewing news article candidates for a satire/political commentary site called NAWWP.

This site is NOT a general religion, crime, terror, or tragedy feed.

KEEP only stories that fit this pattern:
- backlash, outrage, panic, symbolic conflict, overreaction, grievance politics
- fights around schools, books, religion in public life, immigration, identity, gender, DEI, or voting
- school-board, legislative, legal, civic, cultural, or community disputes
- conservative/protectionist panic, exclusion, bans, lawsuits, restrictions, moral panic, public backlash

REJECT stories that are primarily:
- terror attacks
- hate crimes
- shootings
- murders
- assaults
- bombings
- arson
- war
- international conflict
- disaster coverage
- memorial / remembrance coverage
- generic religion news
- generic crime with no strong backlash / policy / culture-war angle

Very important:
A story about a mosque, church, synagogue, or religion does NOT belong unless it is specifically about:
- exclusion
- bans
- school / voucher / curriculum / law fights
- church-state disputes
- public backlash / civic panic
- rights restrictions or ideological conflict

Choose ONE primary topic from the allowed list only.

Allowed topics and slugs:
- Education => education
- Religion / Church-State => religion-church-state
- Immigration / Identity => immigration-identity
- Books / Libraries / Curriculum => books-libraries-curriculum
- Gender / LGBTQ => gender-lgbtq
- DEI / Diversity Backlash => dei-diversity-backlash
- Voting / Civic Panic => voting-civic-panic
- General Culture War => general-culture-war

Return JSON with exactly these keys:
{
  "keep": true,
  "score": 0.0,
  "title": "",
  "source": "",
  "published_at": "",
  "url": "",
  "summary": "",
  "topic": "",
  "section_slug": "",
  "topic_tags": [],
  "tags": []
}
"""


def topic_from_name_or_slug(topic: str = "", section_slug: str = "") -> tuple[str, str]:
    if section_slug and section_slug in TOPIC_BY_SLUG:
        item = TOPIC_BY_SLUG[section_slug]
        return item["topic"], item["section_slug"]

    lowered = (topic or "").strip().lower()
    if lowered in TOPIC_BY_NAME:
        item = TOPIC_BY_NAME[lowered]
        return item["topic"], item["section_slug"]

    return "General Culture War", "general-culture-war"


def normalize_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()

    for item in value:
        text = str(item).strip()
        if not text:
            continue

        lowered = text.lower()
        if lowered in seen:
            continue

        seen.add(lowered)
        cleaned.append(text)

        if len(cleaned) >= limit:
            break

    return cleaned


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_user_prompt(article: dict[str, Any]) -> str:
    allowed_lines = "\n".join(
        f'- {item["topic"]} => {item["section_slug"]}'
        for item in ALLOWED_TOPICS
    )

    return f"""
Review this article candidate and decide whether to keep it.

Article:
Title: {article.get("title", "")}
Source: {article.get("source", "")}
Published: {article.get("published_at", "")}
URL: {article.get("url", "")}
Summary: {article.get("summary", "")}

Pipeline context:
Pipeline score: {article.get("pipeline_score", 1.0)}
Preclassified topic: {article.get("topic", "General Culture War")}
Preclassified section slug: {article.get("section_slug", "general-culture-war")}
Preclassified topic tags: {json.dumps(article.get("topic_tags", []))}
Existing tags: {json.dumps(article.get("tags", []))}

Editorial intent:
Reject real-news tragedy coverage, generic terror/crime stories, generic attacks on houses of worship, and generic religion coverage.
Keep only backlash / panic / exclusion / grievance / culture-war conflict stories.

Rules:
- Choose only ONE topic from the allowed list below
- The section_slug must exactly match the chosen topic
- Return only valid JSON
- Do not include markdown fences

Allowed topics:
{allowed_lines}
""".strip()


def parse_response_json(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`").strip()
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()

    return json.loads(raw_text)


def evaluate_article(article: dict[str, Any]) -> dict[str, Any] | None:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing")

    response = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(article)},
        ],
    )

    raw_text = response.output_text.strip()
    parsed = parse_response_json(raw_text)

    if not parsed.get("keep"):
        return None

    topic, section_slug = topic_from_name_or_slug(
        parsed.get("topic", article.get("topic", "")),
        parsed.get("section_slug", article.get("section_slug", "")),
    )

    reviewed = {
        "title": (parsed.get("title") or article.get("title", "")).strip(),
        "source": (parsed.get("source") or article.get("source", "")).strip(),
        "published_at": (parsed.get("published_at") or article.get("published_at", "")).strip(),
        "url": (parsed.get("url") or article.get("url", "")).strip(),
        "summary": (parsed.get("summary") or article.get("summary", "")).strip(),
        "score": safe_float(parsed.get("score"), 0.0),
        "pipeline_score": safe_float(article.get("pipeline_score", 1.0), 1.0),
        "topic": topic,
        "section_slug": section_slug,
        "topic_tags": normalize_string_list(
            parsed.get("topic_tags", article.get("topic_tags", [])),
            limit=8,
        ),
        "tags": normalize_string_list(
            parsed.get("tags", article.get("tags", [])),
            limit=12,
        ),
    }

    if not reviewed["summary"]:
        reviewed["summary"] = str(article.get("summary", "")).strip()

    if reviewed["score"] < 0:
        reviewed["score"] = 0.0
    if reviewed["score"] > 10:
        reviewed["score"] = 10.0

    return reviewed

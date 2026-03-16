import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY in .env")

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
You are classifying news stories for a satire website.

The site focuses on real news stories involving:
- racial, religious, or cultural overreaction
- panic about immigration, Islam, diversity, schools, or identity
- symbolic "threat to traditional America" narratives
- public backlash, outrage campaigns, school fights, charter school disputes, book bans, and similar incidents

Reject stories that are:
- generic crime
- foreign policy or war news
- unrelated national politics
- opinion columns with no concrete incident
- celebrity or entertainment news
- video game or tech culture stories
- articles whose only relevance is a keyword match

Return JSON only with:
{
  "keep": true or false,
  "score": number from 0 to 10,
  "tags": ["tag1", "tag2", "tag3"],
  "summary": "1-2 sentence neutral summary"
}
"""


def evaluate_article(article: dict[str, Any]) -> dict[str, Any] | None:
    prompt = f"""
Title: {article.get("title", "")}
Source: {article.get("source", "")}
Published At: {article.get("published_at", "")}
Description: {article.get("summary", "")}
URL: {article.get("url", "")}
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "article_review",
                "schema": {
                    "type": "object",
                    "properties": {
                        "keep": {"type": "boolean"},
                        "score": {"type": "number"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 0,
                            "maxItems": 5
                        },
                        "summary": {"type": "string"},
                    },
                    "required": ["keep", "score", "tags", "summary"],
                    "additionalProperties": False,
                },
            }
        },
    )

    output_text = response.output_text.strip()

    try:
        result = json.loads(output_text)
    except json.JSONDecodeError:
        print(f"Skipping article due to bad AI JSON: {article.get('title', '')}")
        return None

    if not result.get("keep", False):
        return None

    article["score"] = float(result.get("score", 0))
    article["tags"] = result.get("tags", [])
    article["summary"] = result.get("summary", article.get("summary", ""))

    return article

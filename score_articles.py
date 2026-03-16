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
You classify news stories for a satire site that tracks U.S. culture-war
panic and outrage narratives.

Keep stories about:
- school board conflicts
- charter or religious school funding fights
- immigration panic
- DEI backlash
- diversity or curriculum controversies
- religion in public life
- protests or outrage around identity or culture

Reject stories about:
- shootings or violent crime
- war or foreign terrorism
- sports
- entertainment
- generic national politics without a cultural conflict
- stories outside the United States

Return JSON only with:

{
  "keep": true or false,
  "score": number from 0 to 10,
  "tags": ["tag1", "tag2"],
  "angle": "short phrase describing the outrage narrative",
  "summary": "1-2 sentence neutral summary"
}
"""


def evaluate_article(article: dict[str, Any]) -> dict[str, Any] | None:
    prompt = f"""
Title: {article.get("title", "")}
Source: {article.get("source", "")}
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
                            "items": {"type": "string"}
                        },
                        "angle": {"type": "string"},
                        "summary": {"type": "string"}
                    },
                    "required": ["keep", "score", "tags", "angle", "summary"],
                    "additionalProperties": False
                }
            }
        },
    )

    output_text = response.output_text.strip()

    try:
        result = json.loads(output_text)
    except json.JSONDecodeError:
        print(f"Bad AI JSON for: {article.get('title', '')}")
        return None

    if not result.get("keep", False):
        return None

    article["score"] = float(result.get("score", 0))
    article["tags"] = result.get("tags", [])
    article["angle"] = result.get("angle", "")
    article["summary"] = result.get("summary", article.get("summary", ""))

    return article

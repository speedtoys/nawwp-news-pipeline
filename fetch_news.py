import json
import os
from datetime import UTC, datetime, timedelta

import requests
from dotenv import load_dotenv

from score_articles import evaluate_article

load_dotenv()

NEWS_API_KEY = (os.getenv("NEWS_API_KEY") or "").strip()
NEWS_API_URL = "https://newsapi.org/v2/everything"

BLOCKED_SOURCES = {
    "Freerepublic.com",
    "Thegatewaypundit.com",
}

BLOCKED_TITLE_TERMS = {
    "witchhunter.exe",
}

KEYWORDS = (
    '"school board" OR mosque OR islam OR immigrant OR "religious school" '
    'OR "book ban" OR "christian values" OR "diversity program" '
    'OR islamophobia OR synagogue OR "charter school"'
)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def is_blocked(article: dict) -> bool:
    source_name = ((article.get("source") or {}).get("name") or "").strip()
    title = (article.get("title") or "").lower()

    if source_name in BLOCKED_SOURCES:
        return True

    for term in BLOCKED_TITLE_TERMS:
        if term in title:
            return True

    return False


def normalize_article(item: dict) -> dict | None:
    title = item.get("title")
    url = item.get("url")

    if not title or not url:
        return None

    return {
        "title": title.strip(),
        "source": (item.get("source") or {}).get("name", "Unknown"),
        "published_at": item.get("publishedAt", iso_z(datetime.now(UTC))),
        "url": url.strip(),
        "summary": (item.get("description") or "").strip(),
        "tags": ["unreviewed"],
        "score": 0,
    }


def dedupe_by_url_and_title(articles: list[dict]) -> list[dict]:
    seen_urls = set()
    seen_titles = set()
    kept = []

    for article in articles:
        url = article["url"].strip().lower()
        title = article["title"].strip().lower()

        if url in seen_urls or title in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(title)
        kept.append(article)

    return kept


def fetch_articles() -> list[dict]:
    if not NEWS_API_KEY:
        raise RuntimeError("Missing NEWS_API_KEY in .env")

    now = datetime.now(UTC)
    from_date = now - timedelta(days=3)

    params = {
        "q": KEYWORDS,
        "language": "en",
        "sortBy": "publishedAt",
        "from": iso_z(from_date),
        "pageSize": 30,
        "apiKey": NEWS_API_KEY,
    }

    response = requests.get(NEWS_API_URL, params=params, timeout=30)

    if response.status_code != 200:
        try:
            error_body = response.json()
        except ValueError:
            error_body = response.text
        raise RuntimeError(f"NewsAPI request failed ({response.status_code}): {error_body}")

    data = response.json()

    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data}")

    raw_articles = data.get("articles", [])

    cleaned = []
    for item in raw_articles:
        if is_blocked(item):
            continue

        normalized = normalize_article(item)
        if normalized is None:
            continue

        cleaned.append(normalized)

    return dedupe_by_url_and_title(cleaned)


def main() -> None:
    fetched_articles = fetch_articles()

    print(f"Fetched {len(fetched_articles)} articles. Scoring with AI...")

    scored = []
    for idx, article in enumerate(fetched_articles, start=1):
        print(f"[{idx}/{len(fetched_articles)}] {article['title']}")
        reviewed = evaluate_article(article)
        if reviewed:
            scored.append(reviewed)

    scored.sort(key=lambda x: x["score"], reverse=True)
    final_articles = scored[:10]

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(final_articles, f, indent=2, ensure_ascii=False)

    print(f"Created news.json with {len(final_articles)} AI-selected articles")


if __name__ == "__main__":
    main()

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

import feedparser
import requests
from dotenv import load_dotenv

from score_articles import evaluate_article

load_dotenv()

NEWS_API_KEY = (os.getenv("NEWS_API_KEY") or "").strip()
NEWS_API_URL = "https://newsapi.org/v2/everything"

ARCHIVE_FILE = "archive.json"
OUTPUT_FILE = "news.json"
RSS_SOURCES_FILE = "rss_sources.json"

NEWSAPI_ENABLED = (os.getenv("NEWSAPI_ENABLED", "true").strip().lower() == "true")
RSS_ENABLED = (os.getenv("RSS_ENABLED", "true").strip().lower() == "true")

NEWSAPI_DAYS_BACK = int((os.getenv("NEWSAPI_DAYS_BACK") or "3").strip())
NEWSAPI_PAGE_SIZE = int((os.getenv("NEWSAPI_PAGE_SIZE") or "40").strip())

RSS_DAYS_BACK = int((os.getenv("RSS_DAYS_BACK") or "7").strip())
RSS_PER_FEED_LIMIT = int((os.getenv("RSS_PER_FEED_LIMIT") or "20").strip())
RSS_MAX_WORKERS = int((os.getenv("RSS_MAX_WORKERS") or "8").strip())

MAX_CANDIDATES_FOR_AI = int((os.getenv("MAX_CANDIDATES_FOR_AI") or "30").strip())
FINAL_ARTICLE_COUNT = int((os.getenv("FINAL_ARTICLE_COUNT") or "12").strip())

KEYWORDS = (
    '"school board" OR mosque OR islam OR immigrant OR "religious school" '
    'OR "book ban" OR "christian values" OR "diversity program" OR islamophobia '
    'OR synagogue OR "charter school" OR DEI OR "ethnic studies" OR "parental rights" '
    'OR "religious liberty" OR voucher OR curriculum OR library OR "faith-based" '
    'OR transgender OR LGBTQ OR "drag queen" OR "prayer in school" '
    'OR immigration OR voter OR election OR ballot'
)

KEYWORD_FILTER_TERMS = {
    "school board",
    "school",
    "teacher",
    "student",
    "classroom",
    "district",
    "voucher",
    "charter school",
    "public school",
    "religious school",
    "mosque",
    "islam",
    "muslim",
    "synagogue",
    "jewish",
    "church",
    "christian",
    "faith-based",
    "religious liberty",
    "prayer",
    "religion",
    "immigrant",
    "immigration",
    "migrant",
    "refugee",
    "border",
    "asylum",
    "identity",
    "ethnic",
    "book ban",
    "banned books",
    "library",
    "librarian",
    "curriculum",
    "reading list",
    "textbook",
    "dei",
    "diversity",
    "equity",
    "inclusion",
    "woke",
    "ethnic studies",
    "transgender",
    "lgbtq",
    "gay",
    "lesbian",
    "nonbinary",
    "pronoun",
    "drag",
    "gender identity",
    "election",
    "voting",
    "ballot",
    "voter",
    "polling place",
    "civic",
    "parental rights",
}

BLOCKED_SOURCES = {
    "Freerepublic.com",
    "Thegatewaypundit.com",
}

BLOCKED_TITLE_TERMS = {
    "witchhunter.exe",
}

SITE_TOPICS = [
    {"topic": "Education", "section_slug": "education"},
    {"topic": "Religion / Church-State", "section_slug": "religion-church-state"},
    {"topic": "Immigration / Identity", "section_slug": "immigration-identity"},
    {"topic": "Books / Libraries / Curriculum", "section_slug": "books-libraries-curriculum"},
    {"topic": "Gender / LGBTQ", "section_slug": "gender-lgbtq"},
    {"topic": "DEI / Diversity Backlash", "section_slug": "dei-diversity-backlash"},
    {"topic": "Voting / Civic Panic", "section_slug": "voting-civic-panic"},
    {"topic": "General Culture War", "section_slug": "general-culture-war"},
]

TOPIC_RULES = [
    {
        "topic": "Education",
        "section_slug": "education",
        "terms": [
            "school board",
            "school",
            "teacher",
            "student",
            "classroom",
            "district",
            "public school",
            "charter school",
            "voucher",
        ],
    },
    {
        "topic": "Religion / Church-State",
        "section_slug": "religion-church-state",
        "terms": [
            "church",
            "christian",
            "muslim",
            "mosque",
            "synagogue",
            "religious liberty",
            "faith-based",
            "prayer",
            "religion",
            "pastor",
        ],
    },
    {
        "topic": "Immigration / Identity",
        "section_slug": "immigration-identity",
        "terms": [
            "immigrant",
            "immigration",
            "migrant",
            "refugee",
            "border",
            "asylum",
            "ethnic",
            "identity",
        ],
    },
    {
        "topic": "Books / Libraries / Curriculum",
        "section_slug": "books-libraries-curriculum",
        "terms": [
            "book ban",
            "banned books",
            "library",
            "librarian",
            "curriculum",
            "reading list",
            "textbook",
            "ethnic studies",
        ],
    },
    {
        "topic": "Gender / LGBTQ",
        "section_slug": "gender-lgbtq",
        "terms": [
            "transgender",
            "lgbtq",
            "gay",
            "lesbian",
            "nonbinary",
            "pronoun",
            "drag",
            "gender identity",
        ],
    },
    {
        "topic": "DEI / Diversity Backlash",
        "section_slug": "dei-diversity-backlash",
        "terms": [
            "dei",
            "diversity",
            "equity",
            "inclusion",
            "affirmative action",
            "ethnic studies",
            "woke",
        ],
    },
    {
        "topic": "Voting / Civic Panic",
        "section_slug": "voting-civic-panic",
        "terms": [
            "election",
            "voting",
            "ballot",
            "polling place",
            "voter",
            "school election",
            "civic",
        ],
    },
]

TOPIC_MAP_BY_NAME = {item["topic"].lower(): item for item in SITE_TOPICS}
TOPIC_MAP_BY_SLUG = {item["section_slug"]: item for item in SITE_TOPICS}

HTML_TAG_RE = re.compile(r"<[^>]+>")
MULTISPACE_RE = re.compile(r"\s+")


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(dt_str: str | None) -> datetime:
    if not dt_str:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def strip_html(text: str) -> str:
    text = unescape(text or "")
    text = HTML_TAG_RE.sub(" ", text)
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def normalize_url(url: str) -> str:
    return (url or "").strip().lower()


def load_json_file(path: str, fallback: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def save_json_file(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_archive() -> list[dict[str, Any]]:
    data = load_json_file(ARCHIVE_FILE, [])
    return data if isinstance(data, list) else []


def save_archive(archive: list[dict[str, Any]]) -> None:
    save_json_file(ARCHIVE_FILE, archive)


def load_rss_sources() -> list[dict[str, Any]]:
    data = load_json_file(RSS_SOURCES_FILE, [])
    if not isinstance(data, list):
        return []

    valid_sources: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        name = (item.get("name") or "").strip()
        url = (item.get("url") or "").strip()
        if not name or not url:
            continue

        valid_sources.append(
            {
                "name": name,
                "url": url,
                "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [],
                "base_weight": item.get("base_weight", 1.0),
                "keyword_boosts": item.get("keyword_boosts", {}) if isinstance(item.get("keyword_boosts"), dict) else {},
                "required_any": item.get("required_any", []) if isinstance(item.get("required_any"), list) else [],
                "default_topic": (item.get("default_topic") or "").strip(),
            }
        )

    return valid_sources


def normalize_article(item: dict[str, Any]) -> dict[str, Any] | None:
    title = strip_html(item.get("title") or "")
    url = (item.get("url") or "").strip()
    if not title or not url:
        return None

    source = item.get("source") or {}
    source_name = source if isinstance(source, str) else (source.get("name") or "Unknown")

    return {
        "title": title,
        "source": str(source_name).strip() or "Unknown",
        "published_at": item.get("published_at") or item.get("publishedAt") or iso_z(datetime.now(UTC)),
        "url": url,
        "summary": strip_html(item.get("summary") or item.get("description") or ""),
        "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [],
        "score": float(item.get("score", 0) or 0),
        "pipeline_score": float(item.get("pipeline_score", 1.0) or 1.0),
    }


def build_text_blob(article: dict[str, Any]) -> str:
    parts = [
        article.get("title", ""),
        article.get("summary", ""),
        article.get("source", ""),
        " ".join(article.get("tags", [])) if isinstance(article.get("tags"), list) else "",
    ]
    return " ".join(parts).lower()


def topic_from_name_or_slug(topic: str = "", section_slug: str = "") -> tuple[str, str]:
    if section_slug and section_slug in TOPIC_MAP_BY_SLUG:
        item = TOPIC_MAP_BY_SLUG[section_slug]
        return item["topic"], item["section_slug"]

    lowered = (topic or "").strip().lower()
    if lowered in TOPIC_MAP_BY_NAME:
        item = TOPIC_MAP_BY_NAME[lowered]
        return item["topic"], item["section_slug"]

    return "General Culture War", "general-culture-war"


def enforce_site_topic(article: dict[str, Any], preferred_topic: str = "", preferred_slug: str = "") -> dict[str, Any]:
    topic, section_slug = topic_from_name_or_slug(preferred_topic, preferred_slug)

    article["topic"] = topic
    article["section_slug"] = section_slug

    topic_tags = article.get("topic_tags", [])
    if not isinstance(topic_tags, list):
        topic_tags = []
    article["topic_tags"] = [str(tag).strip() for tag in topic_tags if str(tag).strip()][:8]

    tags = article.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    article["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()][:12]

    return article


def classify_topic(article: dict[str, Any], default_topic: str = "") -> tuple[str, str, list[str]]:
    blob = build_text_blob(article)

    best_topic = "General Culture War"
    best_slug = "general-culture-war"
    best_matches: list[str] = []
    best_count = 0

    for rule in TOPIC_RULES:
        matches = [term for term in rule["terms"] if term in blob]
        if len(matches) > best_count:
            best_count = len(matches)
            best_topic = rule["topic"]
            best_slug = rule["section_slug"]
            best_matches = matches[:5]

    if best_count == 0 and default_topic:
        mapped_topic, mapped_slug = topic_from_name_or_slug(default_topic, "")
        return mapped_topic, mapped_slug, []

    return best_topic, best_slug, best_matches


def matches_keyword_filter(article: dict[str, Any]) -> bool:
    blob = build_text_blob(article)
    return any(term in blob for term in KEYWORD_FILTER_TERMS)


def is_blocked(article: dict[str, Any]) -> bool:
    source_name = (article.get("source") or "").strip()
    title = (article.get("title") or "").lower()

    if source_name in BLOCKED_SOURCES:
        return True

    return any(term in title for term in BLOCKED_TITLE_TERMS)


def compute_feed_profile_score(article: dict[str, Any], source_profile: dict[str, Any]) -> float:
    blob = build_text_blob(article)

    try:
        score = float(source_profile.get("base_weight", 1.0) or 1.0)
    except (TypeError, ValueError):
        score = 1.0

    required_any = [
        str(term).lower().strip()
        for term in source_profile.get("required_any", [])
        if isinstance(term, str) and term.strip()
    ]
    if required_any and not any(term in blob for term in required_any):
        return 0.0

    keyword_boosts = source_profile.get("keyword_boosts", {})
    if isinstance(keyword_boosts, dict):
        for term, boost in keyword_boosts.items():
            if not isinstance(term, str):
                continue
            if term.lower().strip() in blob:
                try:
                    score *= float(boost)
                except (TypeError, ValueError):
                    pass

    return round(score, 3)


def dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    seen_titles: set[str] = set()

    def rank_key(article: dict[str, Any]) -> tuple[float, datetime]:
        return (
            float(article.get("pipeline_score", 1.0) or 1.0),
            parse_iso(article.get("published_at")),
        )

    for article in articles:
        url_key = normalize_url(article.get("url", ""))
        title_key = (article.get("title", "") or "").strip().lower()

        if not url_key or not title_key:
            continue

        existing = by_url.get(url_key)
        if existing is None or rank_key(article) > rank_key(existing):
            by_url[url_key] = article

    deduped_by_url = list(by_url.values())
    deduped_by_url.sort(key=rank_key, reverse=True)

    final: list[dict[str, Any]] = []
    for article in deduped_by_url:
        title_key = (article.get("title", "") or "").strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        final.append(article)

    return final


def parse_entry_datetime(entry: Any) -> datetime:
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=UTC)
            except Exception:
                pass

    for attr in ("published", "updated"):
        value = getattr(entry, attr, None)
        if value:
            try:
                dt = parsedate_to_datetime(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except Exception:
                pass

    return datetime.now(UTC)


def extract_entry_summary(entry: Any) -> str:
    candidates: list[str] = []

    for attr in ("summary", "description"):
        value = getattr(entry, attr, None)
        if value:
            candidates.append(str(value))

    content = getattr(entry, "content", None)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("value"):
                candidates.append(str(block["value"]))

    for candidate in candidates:
        cleaned = strip_html(candidate)
        if cleaned:
            return cleaned[:800]

    return ""


def fetch_newsapi_articles() -> list[dict[str, Any]]:
    if not NEWSAPI_ENABLED:
        print("NewsAPI disabled")
        return []

    if not NEWS_API_KEY:
        print("Skipping NewsAPI because NEWS_API_KEY is missing")
        return []

    from_date = datetime.now(UTC) - timedelta(days=NEWSAPI_DAYS_BACK)

    params = {
        "q": KEYWORDS,
        "language": "en",
        "sortBy": "publishedAt",
        "from": iso_z(from_date),
        "pageSize": NEWSAPI_PAGE_SIZE,
        "apiKey": NEWS_API_KEY,
    }

    response = requests.get(NEWS_API_URL, params=params, timeout=30)
    if response.status_code != 200:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        raise RuntimeError(f"NewsAPI request failed ({response.status_code}): {body}")

    data = response.json()
    raw_articles = data.get("articles", [])
    if not isinstance(raw_articles, list):
        return []

    articles: list[dict[str, Any]] = []
    for item in raw_articles:
        if not isinstance(item, dict):
            continue

        article = normalize_article(item)
        if article is None:
            continue
        if is_blocked(article):
            continue
        if not matches_keyword_filter(article):
            continue

        article["tags"] = sorted(set(article.get("tags", []) + ["newsapi"]))
        article["pipeline_score"] = 1.0

        topic, section_slug, topic_tags = classify_topic(article)
        article["topic_tags"] = topic_tags
        enforce_site_topic(article, topic, section_slug)

        articles.append(article)

    return dedupe_articles(articles)


def fetch_single_rss_feed(source: dict[str, Any], cutoff_dt: datetime) -> list[dict[str, Any]]:
    source_name = source["name"]
    source_url = source["url"]
    source_tags = source.get("tags", [])
    default_topic = source.get("default_topic", "")

    try:
        feed = feedparser.parse(source_url)
    except Exception as exc:
        print(f"RSS error for {source_name}: {exc}")
        return []

    if getattr(feed, "bozo", 0):
        bozo_exc = getattr(feed, "bozo_exception", None)
        if bozo_exc:
            print(f"RSS warning for {source_name}: {bozo_exc}")

    entries = getattr(feed, "entries", []) or []
    articles: list[dict[str, Any]] = []

    for entry in entries[:RSS_PER_FEED_LIMIT]:
        title = strip_html(getattr(entry, "title", "") or "")
        url = (getattr(entry, "link", "") or "").strip()

        if not title or not url:
            continue

        published_dt = parse_entry_datetime(entry)
        if published_dt < cutoff_dt:
            continue

        article = {
            "title": title,
            "source": source_name,
            "published_at": iso_z(published_dt),
            "url": url,
            "summary": extract_entry_summary(entry),
            "tags": sorted(set(["rss", *source_tags])),
            "score": 0.0,
            "topic_tags": [],
        }

        if is_blocked(article):
            continue
        if not matches_keyword_filter(article):
            continue

        pipeline_score = compute_feed_profile_score(article, source)
        if pipeline_score <= 0:
            continue

        article["pipeline_score"] = pipeline_score

        topic, section_slug, topic_tags = classify_topic(article, default_topic=default_topic)
        article["topic_tags"] = topic_tags
        enforce_site_topic(article, topic, section_slug)

        articles.append(article)

    return articles


def fetch_rss_articles() -> list[dict[str, Any]]:
    if not RSS_ENABLED:
        print("RSS disabled")
        return []

    sources = load_rss_sources()
    if not sources:
        print("No RSS sources configured")
        return []

    cutoff_dt = datetime.now(UTC) - timedelta(days=RSS_DAYS_BACK)
    all_articles: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=RSS_MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_single_rss_feed, source, cutoff_dt): source
            for source in sources
        }

        for future in as_completed(futures):
            source = futures[future]
            try:
                articles = future.result()
                print(f"RSS {source['name']}: {len(articles)} matched")
                all_articles.extend(articles)
            except Exception as exc:
                print(f"RSS failure for {source['name']}: {exc}")

    return dedupe_articles(all_articles)


def fetch_articles() -> list[dict[str, Any]]:
    newsapi_articles = fetch_newsapi_articles()
    rss_articles = fetch_rss_articles()

    merged = dedupe_articles(newsapi_articles + rss_articles)
    merged.sort(
        key=lambda x: (
            float(x.get("pipeline_score", 1.0) or 1.0),
            parse_iso(x.get("published_at")),
        ),
        reverse=True,
    )

    print(
        f"Merged candidate pool: {len(merged)} "
        f"({len(newsapi_articles)} NewsAPI + {len(rss_articles)} RSS before trim)"
    )
    return merged


def main() -> None:
    print("Starting pipeline...")

    archive = load_archive()
    seen_urls = {
        normalize_url(item.get("url", ""))
        for item in archive
        if isinstance(item, dict) and item.get("url")
    }

    fetched_articles = fetch_articles()
    candidate_articles = fetched_articles[:MAX_CANDIDATES_FOR_AI]

    print(
        f"Fetched {len(fetched_articles)} pre-filtered articles total. "
        f"Scoring top {len(candidate_articles)} with AI..."
    )

    reviewed_articles: list[dict[str, Any]] = []

    def score_one_article(args: tuple[int, dict[str, Any]]) -> dict[str, Any] | None:
        idx, article = args
        url_key = normalize_url(article.get("url", ""))

        if url_key in seen_urls:
            print(f"[{idx}/{len(candidate_articles)}] Skipping archived: {article['title']}")
            return None

        print(
            f"[{idx}/{len(candidate_articles)}] Scoring: {article['title']} "
            f"(topic={article.get('topic', 'Unknown')}, pipeline_score={article.get('pipeline_score', 1.0)})"
        )

        try:
            reviewed = evaluate_article(article)
        except Exception as exc:
            print(f"[{idx}/{len(candidate_articles)}] AI scoring failed: {exc}")
            return None

        if reviewed:
            reviewed.setdefault("pipeline_score", article.get("pipeline_score", 1.0))
            reviewed.setdefault("topic_tags", article.get("topic_tags", []))
            reviewed.setdefault("tags", article.get("tags", []))

            reviewed = enforce_site_topic(
                reviewed,
                reviewed.get("topic", article.get("topic", "General Culture War")),
                reviewed.get("section_slug", article.get("section_slug", "general-culture-war")),
            )

        return reviewed

    ai_workers = int((os.getenv("AI_MAX_WORKERS") or "5").strip())

    with ThreadPoolExecutor(max_workers=ai_workers) as executor:
        futures = [
            executor.submit(score_one_article, (idx, article))
            for idx, article in enumerate(candidate_articles, start=1)
        ]

        for future in as_completed(futures):
            reviewed = future.result()
            if reviewed:
                url_key = normalize_url(reviewed.get("url", ""))
                if url_key not in seen_urls:
                    reviewed_articles.append(reviewed)
                    archive.append(reviewed)
                    seen_urls.add(url_key)

    reviewed_articles.sort(
        key=lambda x: (
            float(x.get("score", 0) or 0),
            float(x.get("pipeline_score", 1.0) or 1.0),
            parse_iso(x.get("published_at")),
        ),
        reverse=True,
    )

    final_articles = reviewed_articles[:FINAL_ARTICLE_COUNT]

    save_json_file(OUTPUT_FILE, final_articles)
    save_archive(archive)

    print(f"Created {OUTPUT_FILE} with {len(final_articles)} AI-selected articles")
    print(f"Archive now contains {len(archive)} total articles")


if __name__ == "__main__":
    main()

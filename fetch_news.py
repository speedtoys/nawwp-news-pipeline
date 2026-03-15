import json
from datetime import datetime

sample_articles = [
    {
        "title": "Sample Story One",
        "source": "Example News",
        "published_at": datetime.utcnow().isoformat() + "Z",
        "url": "https://example.com/story-1",
        "summary": "This is a test summary for the first sample story.",
        "tags": ["test", "news"],
        "score": 7.5,
    },
    {
        "title": "Sample Story Two",
        "source": "Example Daily",
        "published_at": datetime.utcnow().isoformat() + "Z",
        "url": "https://example.com/story-2",
        "summary": "This is a test summary for the second sample story.",
        "tags": ["test", "feed"],
        "score": 8.1,
    },
]

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(sample_articles, f, indent=2)

print("Created news.json")

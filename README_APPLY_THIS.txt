Unzip this archive from the root of your repo.

This bundle replaces:
- rss_sources.json
- fetch_news.py
- score_articles.py

What it changes:
- much broader source coverage
- many more Google News query families
- looser discovery prefilter
- boundary-safe anti-trans matching
- hard rejection of real crime / violence stories
- rolling 7-day visible publication window

Recommended run:
IGNORE_SEEN=1 python fetch_news.py

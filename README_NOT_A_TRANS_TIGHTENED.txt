Unzip this from the repo root. It replaces only score_articles.py.

Then run:
IGNORE_SEEN=1 python fetch_news.py

What changed:
- Tightened Not A Trans… matching
- Requires: sex-crime signal + legal-status signal + explicit conservative/culture-war hypocrisy signal
- Rejects immigration/status-only or generic church-title false positives
- Example like 'Illegal immigrant operating as pastor arrested' should now reject

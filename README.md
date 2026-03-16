# NAWWP News Pipeline

GitHub Pages-ready pipeline for collecting U.S. culture-war / identity-outrage stories.

## Files
- `fetch_news.py` — fetches RSS + Google News RSS, filters, scores, writes site output
- `score_articles.py` — heuristic/model scoring
- `rss_sources.json` — feed and query config
- `.github/workflows/build.yml` — GitHub Actions scheduler
- `docs/index.html` / `docs/news.json` — generated static site output

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
IGNORE_SEEN=1 python fetch_news.py
```

## GitHub Pages
Enable Pages from:
- Branch: `main`
- Folder: `/docs`

## GitHub Actions secret
Add:
- `OPENAI_API_KEY`

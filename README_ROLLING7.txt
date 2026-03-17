Unzip this archive from the root of your repo.

It replaces:
- fetch_news.py

What this new file does:
- fetches stories up to 7 days old
- keeps accepted keep/wings stories visible for a rolling 7-day window
- ages stories out automatically after 7 days
- prints reviewed and published totals at the end of each run

Default rolling window:
- ROLLING_DAYS=7

Run with:
IGNORE_SEEN=1 python fetch_news.py

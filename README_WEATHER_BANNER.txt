Unzip this from the repo root. It replaces rss_sources.json, score_articles.py, and fetch_news.py,
and adds docs/images/weather_super_snowflakey.png.
Then run:
IGNORE_SEEN=1 python fetch_news.py
This updates the site tagline and adds the weather graphic to the front page only, directly below the tagline.

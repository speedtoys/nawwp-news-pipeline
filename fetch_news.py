[
  {
    "name": "The Hill",
    "url": "https://thehill.com/feed/",
    "tags": ["politics", "national"],
    "base_weight": 1.1,
    "default_topic": "General Culture War",
    "keyword_boosts": {
      "school board": 1.4,
      "voucher": 1.3,
      "religious school": 1.5,
      "dei": 1.2,
      "immigration": 1.2,
      "transgender": 1.2
    },
    "required_any": ["school", "religion", "immigration", "diversity", "library", "gender"]
  },
  {
    "name": "Religion News Service",
    "url": "https://religionnews.com/feed/",
    "tags": ["religion", "national"],
    "base_weight": 1.3,
    "default_topic": "Religion / Church-State",
    "keyword_boosts": {
      "christian": 1.2,
      "muslim": 1.4,
      "mosque": 1.5,
      "synagogue": 1.4,
      "faith-based": 1.5,
      "religious liberty": 1.5,
      "prayer": 1.3
    },
    "required_any": ["christian", "muslim", "mosque", "school", "church", "religious", "synagogue"]
  },
  {
    "name": "Texas Tribune",
    "url": "https://www.texastribune.org/feeds/news/",
    "tags": ["education", "state"],
    "base_weight": 1.35,
    "default_topic": "Education",
    "keyword_boosts": {
      "school board": 1.6,
      "curriculum": 1.3,
      "book ban": 1.5,
      "voucher": 1.6,
      "prayer": 1.3,
      "religious school": 1.4
    },
    "required_any": ["school", "book", "voucher", "curriculum", "religion", "library"]
  },
  {
    "name": "Chalkbeat",
    "url": "https://www.chalkbeat.org/rss/index.xml",
    "tags": ["education", "schools"],
    "base_weight": 1.3,
    "default_topic": "Education",
    "keyword_boosts": {
      "school board": 1.4,
      "curriculum": 1.4,
      "book ban": 1.5,
      "charter school": 1.3,
      "voucher": 1.3
    },
    "required_any": ["school", "student", "curriculum", "library", "teacher", "district"]
  },
  {
    "name": "NPR",
    "url": "https://feeds.npr.org/1001/rss.xml",
    "tags": ["national", "mainstream"],
    "base_weight": 0.95,
    "default_topic": "General Culture War",
    "keyword_boosts": {
      "immigration": 1.2,
      "religious liberty": 1.2,
      "school board": 1.2,
      "transgender": 1.2,
      "book ban": 1.2
    },
    "required_any": ["school", "immigration", "religion", "library", "gender", "dei"]
  },
  {
    "name": "ProPublica",
    "url": "https://www.propublica.org/feeds/propublica/main",
    "tags": ["investigations", "national"],
    "base_weight": 1.1,
    "default_topic": "General Culture War",
    "keyword_boosts": {
      "school": 1.2,
      "immigration": 1.2,
      "religion": 1.2,
      "voting": 1.2,
      "dei": 1.2
    },
    "required_any": ["school", "immigration", "religion", "voting", "library", "diversity"]
  },
  {
    "name": "Associated Press",
    "url": "https://apnews.com/hub/ap-top-news?output=rss",
    "tags": ["wire", "national"],
    "base_weight": 0.9,
    "default_topic": "General Culture War",
    "keyword_boosts": {
      "school board": 1.3,
      "religious school": 1.4,
      "immigration": 1.2,
      "dei": 1.2,
      "transgender": 1.2
    },
    "required_any": ["school", "religion", "immigration", "library", "dei", "gender", "voting"]
  }
]

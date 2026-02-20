"""
WHY — scraper.py
Busca notícias do dia anterior via Google News RSS.
Sort múltiplos tópicos/tickers configuráveis.
"""

import feedparser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


TOPICS = [
    {"label": "Markets",    "query": "stock market"},
    {"label": "Tesla",      "query": "TSLA Tesla"},
    {"label": "AI",         "query": "artificial intelligence"},
    {"label": "Economy",    "query": "economy inflation"},
    {"label": "Tech",       "query": "technology startups"},
    {"label": "Energy",     "query": "oil energy"},
]

MAX_PER_TOPIC = 8
DAYS_BACK     = 1


def _is_recent(published_str: str, days_back: int = DAYS_BACK) -> bool:
    try:
        pub_dt = parsedate_to_datetime(published_str)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        return pub_dt >= cutoff
    except Exception:
        return True


def fetch_topic(topic: dict) -> dict:
    query = topic["query"].replace(" ", "+")
    url   = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    feed  = feedparser.parse(url)
    articles = []

    for entry in feed.entries[:MAX_PER_TOPIC * 2]:
        if not _is_recent(entry.get("published", "")):
            continue
        title_full = entry.get("title", "")
        if " - " in title_full:
            *title_parts, source = title_full.rsplit(" - ", 1)
            title = " - ".join(title_parts)
        else:
            title  = title_full
            source = entry.get("source", {}).get("title", "Unknown")
        articles.append({
            "title":     title.strip(),
            "link":      entry.get("link", "#"),
            "published": entry.get("published", ""),
            "source":    source.strip(),
        })
        if len(articles) >= MAX_PER_TOPIC:
            break

    return {"label": topic["label"], "query": topic["query"], "articles": articles}


def fetch_all(topics: list = TOPICS) -> dict:
    now       = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    results   = []
    for topic in topics:
        print(f"⏳ Buscando: {topic['label']}...")
        result = fetch_topic(topic)
        print(f"   ✅ {len(result['articles'])} artigos")
        results.append(result)
    return {
        "generated_at": now.isoformat(),
        "date_label":   yesterday.strftime("Yesterday, %b %d"),
        "topics":       results,
    }

def fetch_stock_news(ticker):
    """
    Busca as manchetes mais recentes do Google News via RSS.
    """
    
    search_query = f"{ticker}+stock"
    url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"
    
    print(f"Buscando notícias para: {ticker}...")
    feed = feedparser.parse(url)
    
    news_list = []
    

    for entry in feed.entries[:10]:
        news_list.append({
            'title': entry.title,
            'link': entry.link,
            'published': entry.published
        })
    
    return news_list

if __name__ == "__main__":
    
    test_ticker = "TSLA"  
    results = fetch_stock_news(test_ticker)
    
    for i, news in enumerate(results, 1):
        print(f"{i}. {news['title']}")
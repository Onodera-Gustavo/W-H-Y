import feedparser

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
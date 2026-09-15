import pytest

from why import quality

# real titles from the feed (September 2026) that are templates, not news
DROPPED = [
    ("Are Investors Undervaluing Global Partners (GLP) Right Now?", "stock_screener"),
    ("Are Investors Undervaluing Banco Bilbao Viscaya Argentaria (BBVA) Right Now?",
     "stock_screener"),
    ("Are Investors Undervaluing Abercrombie & Fitch (ANF) Right Now?", "stock_screener"),
    ("Are Computer and Technology Stocks Lagging ASML Holding (ASML) This Year?",
     "stock_screener"),
    ("GTN vs. NFLX: Which Stock Is the Better Value Option?", "stock_screener"),
    ("Is Nvidia (NVDA) Outperforming Other Computer and Technology Stocks This Year?",
     "stock_screener"),
    ("symbol__ Stock Quote Price and Forecast", "unrendered_template"),
    ("Stock price for {{ticker}} today", "unrendered_template"),
    ("TSLA Stock Quote Price and Forecast", "quote_page"),
    ("Nvidia Stock Price Today", "quote_page"),
    ("Transformer Oil Market worth $2.87 billion by 2031 | MarketsandMarkets™",
     "market_research_release"),
    ("   ", "empty"),
]  # fmt: skip

# real headlines that sit close to a rule and must stay
KEPT = [
    "Why is Boot Barn stock sliding today?",
    "Owens Corning (OC) Faces A Fresh Test Following Its Share Price Slide And Undervalued View",
    "Tesla (TSLA) Stock Dips as Long-Awaited Roadster Unveiling Gets Official October 1 Date",
    "NIO vs. Tesla: Which EV Stock Has the Better Investment Case?",
    "ServiceNow vs. Palantir: I'd Rather Own This AI Stock",
    "Nvidia Triggers Key Signals As AI Warnings Mount; Is Nvidia A Sell Now?",
    "USA Compression Partners: Time To Head For The Hills And Do Not Look Back (NYSE:USAC)",
    "Current price of oil as of Sept. 15, 2026",
    "Real Feelings For Social Intelligence | Newswise",
    "Opinion | How to keep AI from going rogue? Start with a 30-day stand-down.",
    "Warren Buffett sends stark warning to stock market investors",
    "Could Tesla stock really hit $400 again this year?",
    "Tesla rebounds with 52% US EV market share desp...",
    "Tesla, Microsoft and Amazon Forecast: Tech Stocks Diverge",
    "Elon Musk's $1 Trillion Pay Package Needs Tesla to Hit an $8.5 Trillion Market Cap. "
    "Here's What That Means for Shareholders.",
    "10-Year Treasury Yield Just Passed 5%, Here's What Happened To The Market When The Same "
    "Thing Happened In 2007",
    "30 New 4-Star Stocks This Week",
    # constructed near misses
    "Are Investors Undervaluing Tech Stocks After the Selloff?",
    "Tesla stock price today: shares fall 3% after the delivery miss",
    "Why stock prices and bond yields are moving together",
    "AI chip market to reach $500 billion by 2030 | Reuters",
    "Stock market worth $50 trillion by 2030, Goldman says",
    "Housing market report shows prices up in 2026 | CNN",
]


@pytest.mark.parametrize(("title", "rule"), DROPPED)
def test_template_titles_are_flagged_with_their_rule(title, rule):
    assert quality.low_quality_reason(title) == rule
    assert quality.is_low_quality(title)


@pytest.mark.parametrize("title", KEPT)
def test_near_miss_real_headlines_are_kept(title):
    assert quality.low_quality_reason(title) is None


def test_every_rule_is_documented_and_removes_its_own_example():
    names = [rule.name for rule in quality.RULES]
    assert len(names) == len(set(names))
    for rule in quality.RULES:
        assert rule.description and rule.patterns
        assert quality.low_quality_reason(rule.example) == rule.name


def test_split_keeps_order_and_separates_the_dropped_records():
    records = [{"title": "Oil slides"}, {"title": DROPPED[0][0]}, {"title": "Fed holds rates"}]
    kept, dropped = quality.split(records)
    assert [r["title"] for r in kept] == ["Oil slides", "Fed holds rates"]
    assert dropped == [records[1]]

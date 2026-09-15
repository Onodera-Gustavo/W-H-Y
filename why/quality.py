"""Headline quality filter: feed items that are not news.

Google News search also returns pages generated from a template (stock screeners, quote pages,
market research releases) and, now and then, a page whose template never rendered. They crowd
real headlines out of an edition capped at a few items per topic and pull a topic's sentiment
toward whatever the template says.

The rules are deliberately narrow. Each one describes the shape of a known template, never a
topic or a word that real news also uses, and the tests keep near-miss real headlines next to
every rule. Missing some junk costs one slot in the edition; dropping a real headline would
silently hide news, so when in doubt a rule does not match.

The filter runs twice: at ingest, before the per topic cap, so junk never lands in the raw
files; and when exports are built, so titles stored before a rule existed are hidden without
rewriting raw data. Changing a rule therefore changes the site on the next export."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

# a ticker in parentheses, as screener templates print it: (GLP), (BRK.B), (NYSE:USAC)
_TICKER = r"\((?:[A-Z]{2,6}:)?[A-Z]{1,5}(?:[.-][A-Z]{1,2})?\)"


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    example: str  # a real title from the feed that the rule removes
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, title: str) -> bool:
        return any(pattern.search(title) for pattern in self.patterns)


def _rule(name: str, description: str, example: str, *patterns: str) -> Rule:
    return Rule(name, description, example, tuple(re.compile(p) for p in patterns))


RULES: tuple[Rule, ...] = (
    _rule(
        "unrendered_template",
        "a template placeholder that was never filled in",
        "symbol__ Stock Quote Price and Forecast",
        r"[A-Za-z0-9]__|__[A-Za-z0-9]",  # symbol__, __name__
        r"\{\{.*?\}\}|\$\{.*?\}",  # {{ticker}}, ${name}
        r"\[object \w+\]",
    ),
    _rule(
        "stock_screener",
        "screener articles generated for any ticker (Zacks style, syndicated by Yahoo Finance)",
        "Are Investors Undervaluing Global Partners (GLP) Right Now?",
        rf"^Are Investors Undervaluing .+ {_TICKER} Right Now\?$",
        rf"^Are .+ Stocks Lagging .+ {_TICKER} This Year\?$",
        rf"^Is .+ {_TICKER} Outperforming Other .+ Stocks This Year\?$",
        rf"^Is .+ {_TICKER} Stock Undervalued Right Now\?$",
        rf"^Should Value Investors Buy .+ {_TICKER} Stock\?$",
        rf"^Here's Why .+ {_TICKER} is a Strong (?:Value|Growth|Momentum) Stock$",
        r"^.+ vs\. .+: Which Stock Is the Better Value Option\?$",
    ),
    _rule(
        "quote_page",
        "a stock quote page: the whole title is a name plus quote page words",
        "TSLA Stock Quote Price and Forecast",
        r"(?i)^[^:?!.]{0,60}?\b(?:stock|share)s?\s+(?:price|quote)s?"
        r"(?:\s*(?:,|&|and|\||-)?\s*"
        r"(?:price|prices|quote|quotes|forecast|news|chart|charts|history|today|live|overview))+"
        r"\s*$",
    ),
    _rule(
        "market_research_release",
        "a market size press release signed by a research firm",
        "Transformer Oil Market worth $2.87 billion by 2031 | MarketsandMarkets™",
        r"(?i)^(?=.*\bmarket\b.{0,40}\b(?:size|share|worth|to\s+reach|revenue)\b)"
        r"(?=.*\b20\d\d\b)"
        r"(?=.*(?:\bCAGR\b|\|[^|]*(?:markets|research|insights|intelligence)\W*$))",
    ),
)


def low_quality_reason(title: str | None) -> str | None:
    """Name of the first rule the title matches, "empty" for a blank title, None when it looks
    like news."""
    title = (title or "").strip()
    if not title:
        return "empty"
    for rule in RULES:
        if rule.matches(title):
            return rule.name
    return None


def is_low_quality(title: str | None) -> bool:
    return low_quality_reason(title) is not None


def split(records: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """(kept, dropped) raw records, order preserved."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for record in records:
        (dropped if is_low_quality(record.get("title")) else kept).append(record)
    return kept, dropped

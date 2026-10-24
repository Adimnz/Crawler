"""Public-feed catalogue. Availability is measured by polling, never assumed."""

CATALOG_VERSION = 2

# Editorial role describes how material can be used, not its factual accuracy.
EXTRA_FEEDS = [
    ("bbc-business", "BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "BBC", "reporting", "Markets"),
    ("npr-business", "NPR Business", "https://feeds.npr.org/1006/rss.xml", "NPR", "reporting", "Economics"),
    ("guardian-business", "The Guardian Business", "https://www.theguardian.com/uk/business/rss", "The Guardian", "reporting", "Markets"),
    ("aljazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", "reporting", "Politics"),
    ("dw", "Deutsche Welle", "https://rss.dw.com/rdf/rss-en-all", "Deutsche Welle", "reporting", "Politics"),
    ("france24", "France 24", "https://www.france24.com/en/rss", "France 24", "reporting", "Politics"),
    ("globalvoices", "Global Voices", "https://globalvoices.org/feed/", "Global Voices", "reporting", "Politics"),
    ("bellingcat", "Bellingcat", "https://www.bellingcat.com/feed/", "Bellingcat", "reporting", "Investigations"),
    ("icij", "ICIJ", "https://www.icij.org/feed/", "ICIJ", "reporting", "Investigations"),
    ("404media", "404 Media", "https://www.404media.co/rss/", "404 Media", "reporting", "Technology"),
    ("restofworld", "Rest of World", "https://restofworld.org/feed/latest/", "Rest of World", "reporting", "Technology"),
    ("capitalmain", "Capital & Main", "https://capitalandmain.com/feed", "Capital & Main", "reporting", "Economics"),
    ("carbonbrief", "Carbon Brief", "https://www.carbonbrief.org/feed/", "Carbon Brief", "reporting", "Climate"),
    ("grist", "Grist", "https://grist.org/feed/", "Grist", "reporting", "Climate"),
    ("calculatedrisk", "Calculated Risk", "https://www.calculatedriskblog.com/feeds/posts/default?alt=rss", "Calculated Risk", "commentary", "Economics"),
    ("ritholtz", "The Big Picture — Barry Ritholtz", "https://ritholtz.com/feed/", "Barry Ritholtz", "commentary", "Markets"),
    ("damodaran", "Musings on Markets — Aswath Damodaran", "https://aswathdamodaran.blogspot.com/feeds/posts/default?alt=rss", "Aswath Damodaran", "commentary", "Markets"),
    ("marginalrevolution", "Marginal Revolution", "https://marginalrevolution.com/feed", "Marginal Revolution", "commentary", "Economics"),
    ("wealthcommonsense", "A Wealth of Common Sense", "https://awealthofcommonsense.com/feed/", "Ben Carlson", "commentary", "Markets"),
    ("dollarsdata", "Of Dollars and Data", "https://ofdollarsanddata.com/feed/", "Nick Maggiulli", "commentary", "Markets"),
    ("noahpinion", "Noahpinion", "https://www.noahpinion.blog/feed", "Noah Smith", "commentary", "Economics"),
    ("bignewsletter", "BIG — Matt Stoller", "https://www.thebignewsletter.com/feed", "Matt Stoller", "commentary", "Economics"),
    ("pew", "Pew Research Center", "https://www.pewresearch.org/feed/", "Pew Research Center", "survey", "Economics"),
    ("ipsos", "Ipsos research", "https://www.ipsos.com/en/rss.xml", "Ipsos", "survey", "Economics"),
    ("hn", "Hacker News discussions", "https://news.ycombinator.com/rss", "Hacker News", "community", "Technology"),
    ("hn-finance", "Hacker News finance discussions (via HNRSS)", "https://hnrss.org/newest?q=finance", "Hacker News", "community", "Markets"),
    ("money-stackexchange", "Personal Finance & Money — Stack Exchange", "https://money.stackexchange.com/feeds", "Stack Exchange", "community", "Markets"),
    ("economics-stackexchange", "Economics — Stack Exchange", "https://economics.stackexchange.com/feeds", "Stack Exchange", "community", "Economics"),
]

PURPOSES = {
    "reporting": "Publisher reporting and supplied summaries; follow the original for context.",
    "primary": "Official releases for policy, institutions and economic events.",
    "commentary": "Named analysis and research leads; opinions require independent corroboration.",
    "survey": "Published survey research; inspect population, dates, sampling and methodology.",
    "community": "Public questions and discussion leads; not representative polling or verified facts.",
    "discovery": "Headline discovery links; retrieve an accessible original before citing as evidence.",
    "marketdata": "Structured provider observations with instrument identity and timestamps.",
}

# Upgrade only these known catalogue endpoints; user-edited URLs stay untouched.
URL_REPAIRS = {
    "yahoo-finance": ("https://finance.yahoo.com/news/rssindex", "https://finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US"),
    "propublica": ("https://feeds.propublica.org/propublica/main", "https://www.propublica.org/feeds/propublica/main"),
    "calculatedrisk": ("https://www.calculatedriskblog.com/feeds/posts/default?alt=rss", "https://feeds.feedburner.com/CalculatedRisk"),
}


def catalogue(defaults):
    sources = [dict(source) for source in defaults]
    sources.extend({"id": key, "name": name, "url": url, "family": family, "contentRole": role,
                    "category": category, "tier": "social" if role == "community" else "specialist",
                    "kind": "rss", "language": "en", "region": "", "geographyVerified": False,
                    "enabled": True, "interval": 3600000 if role in {"commentary", "survey", "community"} else 900000}
                   for key, name, url, family, role, category in EXTRA_FEEDS)
    sources.append({"id": "hn-api", "name": "Hacker News finance discussions (Algolia API)",
                    "url": "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=finance&hitsPerPage=20",
                    "family": "Hacker News", "contentRole": "community", "category": "Markets", "tier": "social",
                    "kind": "json", "language": "en", "enabled": True, "interval": 3600000,
                    "config": {"itemsPath": "hits", "recordType": "document",
                               "urlTemplate": "https://news.ycombinator.com/item?id={value}", "urlValuePath": "objectID",
                               "fields": {"title": "title", "text": "title", "publishedAt": "created_at"}}})
    for source in sources:
        if source["id"] in URL_REPAIRS:
            source["url"] = URL_REPAIRS[source["id"]][1]
        if source["id"] in {"democracynow", "calculatedrisk"}:
            source["config"] = {"httpsArticleHosts": ["www.democracynow.org" if source["id"] == "democracynow" else "www.calculatedriskblog.com"]}
        role = source.get("contentRole") or ("discovery" if source["id"] in {"googlenews", "flipboard", "reuters"}
                else "marketdata" if source["kind"] != "rss" else "primary" if source["tier"] == "primary" else "reporting")
        source.update(contentRole=role, purpose=PURPOSES[role], catalogVersion=CATALOG_VERSION)
        source.setdefault("interval", 600000)
        if source["id"] == "reuters":
            source["purpose"] = "Reuters headline discovery via Google News. Direct Reuters delivery requires an authorized provider connection."
        if source["id"] == "flipboard":
            source["purpose"] = "Public Flipboard discovery feed; availability depends on the publisher/profile. A blocked feed contributes no evidence."
        if source["id"] == "yahoo-finance":
            source["purpose"] = "Yahoo Finance headlines for SPY market context. This endpoint supplies reporting, not a live price stream; collection depends on publisher access."
    return sources

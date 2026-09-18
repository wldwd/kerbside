"""Find working RSS/Atom feeds for websites.

Run:  python find_feeds.py                  (checks the sites listed below)
  or: python find_feeds.py https://site.org (checks the sites you give it)
"""

import socket
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import feedparser

SITES = [
    "https://betterstreets.org.au",
    "https://www.victoriawalks.org.au",
    "https://www.pedalpower.org.au",
    "https://www.amygillett.org.au",
    "https://bikesa.asn.au",
    "https://www.committeeforperth.com.au",
    "https://www.planning.org.au",
    "https://patrec.org",
    "https://www.audrc.org",
    "https://cur.org.au",
    "https://www.rmit.edu.au/research/centres-collaborations/centre-for-urban-research",
    "https://www.auscycling.org.au",
    "https://www.heartfoundation.org.au",
    "https://thelabofthought.co",
]

# Feed addresses that many website systems use
COMMON_PATHS = [
    "feed/", "rss/", "rss.xml", "feed.xml", "atom.xml", "index.xml",
    "news/feed/", "news/rss/", "blog/feed/", "news.rss",
    "news?format=rss", "blog?format=rss",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (feed finder for Kerbside)"}

# Give up on any site that takes longer than this (seconds)
socket.setdefaulttimeout(15)


class FeedLinkFinder(HTMLParser):
    """Collects <link rel="alternate" type="application/rss+xml"> tags from a page."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        rel = (a.get("rel") or "").lower()
        kind = (a.get("type") or "").lower()
        if "alternate" in rel and ("rss" in kind or "atom" in kind) and a.get("href"):
            self.links.append(a["href"])


def open_page(url):
    """Return the final address (after redirects) and the page's HTML."""
    with urlopen(Request(url, headers=HEADERS)) as response:
        return response.geturl(), response.read().decode("utf-8", errors="replace")


def count_items(url):
    """How many stories a feed link contains (0 if it isn't a feed)."""
    try:
        return len(feedparser.parse(url, agent=HEADERS["User-Agent"]).entries)
    except Exception:
        return 0


def find_feeds(site):
    print(f"\n{site}")
    candidates = []
    base = site

    # 1. Feed links advertised in the page's code
    try:
        base, page = open_page(site)
        if base.rstrip("/") != site.rstrip("/"):
            print(f"  (redirects to {base})")
        finder = FeedLinkFinder()
        finder.feed(page)
        candidates += [urljoin(base, href) for href in finder.links]
    except Exception as error:
        print(f"  Could not open site: {error}")

    # 2. Common feed addresses, from the site root and from the page itself
    root = urljoin(base, "/")
    page_dir = base.rstrip("/") + "/"
    for path in COMMON_PATHS:
        candidates.append(urljoin(root, path))
        if page_dir != root:
            candidates.append(urljoin(page_dir, path))

    found = False
    for url in dict.fromkeys(candidates):  # removes repeats, keeps order
        items = count_items(url)
        if items:
            print(f"  FOUND  {url}  ({items} stories)")
            found = True
    if not found:
        print("  No feed found")


if __name__ == "__main__":
    for site in sys.argv[1:] or SITES:
        find_feeds(site)
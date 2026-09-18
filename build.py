"""Build the Kerbside page from feeds.yaml."""

import calendar
import html
import json
import re
import textwrap
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import feedparser
import yaml

# Where saved stories live between runs
HISTORY_FILE = Path("data/stories.json")

# Folder that GitHub Pages publishes
SITE_DIR = Path("docs")

# Temporary: list the publishers removed as "not Australian"
SHOW_REMOVED_PUBLISHERS = False


# ---------- Part 1: load settings and fetch feeds ----------

def load_settings(path="feeds.yaml"):
    """Read the settings file and return it as a dictionary."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def google_news_feeds(settings):
    """Turn each Google News search in the settings into a feed entry."""
    days = settings["site"]["google_news_days"]
    feeds = []
    for search in settings.get("google_news", []):
        query = quote_plus(f"{search['query']} when:{days}d")
        feeds.append({
            "name": f"Google News - {search['name']}",
            "url": f"https://news.google.com/rss/search?q={query}&hl=en-AU&gl=AU&ceid=AU:en",
            "source_type": "News",
            "filter": False,
            "google_news": True,
            "tag": search.get("tag"),
        })
    return feeds


def fetch_feed(feed):
    """Download one feed and return its stories as simple dictionaries."""
    parsed = feedparser.parse(feed["url"], agent="Kerbside/1.0")

    # 'bozo' means feedparser hit a problem; only give up if nothing came back
    if parsed.bozo and not parsed.entries:
        print(f"  Problem with {feed['name']}: {parsed.bozo_exception}")
        return []

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stories = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        source_name = feed["name"]
        publisher_site = ""

        # Google News items say who really published the story
        if feed.get("google_news"):
            publisher = entry.get("source", {})
            source_name = publisher.get("title", source_name)
            publisher_site = publisher.get("href", "")
            suffix = f" - {source_name}"
            if title.endswith(suffix):
                title = title[: -len(suffix)]

        stories.append({
            "title": title,
            "link": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "published": entry.get("published_parsed") or entry.get("updated_parsed"),
            "first_seen": now,
            "source": source_name,
            "found_via": feed["name"],
            "source_type": feed["source_type"],
            "filter": feed.get("filter", False),
            "fixed_region": feed.get("region"),
            "publisher_site": publisher_site,
            "google_news": feed.get("google_news", False),
            "search_tags": [feed["tag"]] if feed.get("tag") else [],
        })
    return stories


# ---------- Part 2: clean, filter, de-duplicate and tag ----------

def clean_text(raw, max_length=300):
    """Remove HTML, decode symbols like &amp;, tidy spaces and shorten."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return textwrap.shorten(text, width=max_length, placeholder="…")


def find_matches(text, words):
    """Return the words from the list that appear in the text (whole words, any case)."""
    return [w for w in words
            if re.search(r"\b" + re.escape(str(w)) + r"\b", text, re.IGNORECASE)]


def to_datetime(value):
    """Convert a feed date (or an existing datetime) into a UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)


def title_key(title):
    """Simplify a title so near-identical headlines count as duplicates."""
    title = title.rsplit(" - ", 1)[0]
    return re.sub(r"[^a-z0-9]", "", title.lower())


def host_of(site):
    """Get the website name from a link, e.g. 'www.abc.net.au'."""
    return (urlparse(site).hostname or "").lower()


def on_domain(host, domains):
    """True if host is one of the domains or a subdomain of one."""
    return any(host == d or host.endswith("." + d) for d in domains)


def is_australian(host, extra_domains):
    """True if a website ends in .au or is on the extra list."""
    return host.endswith(".au") or on_domain(host, extra_domains)


def process_stories(stories, settings):
    """Keep relevant, recent, unique Australian stories and add tags."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings["site"]["keep_days"])
    extra_domains = settings.get("australian_sources", {}).get("extra_domains", [])
    publisher_regions = settings.get("publisher_regions", {})
    blocked = [b.lower() for b in settings.get("blocked_publishers", [])]

    seen_links, seen_titles = {}, {}   # link/title -> story already kept
    kept = []
    removed = Counter()
    removed_publishers = Counter()

    for story in stories:
        story["summary"] = clean_text(story["summary"])
        story["published"] = to_datetime(story["published"])
        text = f"{story['title']} {story['summary']}"
        host = host_of(story["publisher_site"])

        if story["published"] and story["published"] < cutoff:
            removed["too old"] += 1
            continue

        if story["google_news"] and not is_australian(host, extra_domains):
            removed["not Australian"] += 1
            removed_publishers[f"{story['source']} ({host})"] += 1
            continue

        if any(b in story["source"].lower() for b in blocked):
            removed["blocked publisher"] += 1
            continue

        if find_matches(text, settings["exclude_keywords"]):
            removed["excluded word"] += 1
            continue

        if story["filter"] and not find_matches(text, settings["relevance_keywords"]):
            removed["not relevant"] += 1
            continue

        # Duplicates: keep the first copy but give it the other search's tags
        key = title_key(story["title"])
        original = seen_links.get(story["link"]) or (seen_titles.get(key) if key else None)
        if original:
            for tag in story["search_tags"]:
                if tag not in original["search_tags"]:
                    original["search_tags"].append(tag)
            removed["duplicate"] += 1
            continue
        seen_links[story["link"]] = story
        if key:
            seen_titles[key] = story
        kept.append(story)

    # Tag after de-duplication so merged search tags are included
    for story in kept:
        text = f"{story['title']} {story['summary']}"
        host = host_of(story["publisher_site"])

        tags = [tag
                for group in settings["tag_groups"].values()
                for tag, words in group.items()
                if find_matches(text, words)]
        for tag in story["search_tags"]:
            if tag not in tags:
                tags.append(tag)
        story["tags"] = tags

        # Regions: fixed feed region, then publisher region, then places mentioned
        regions = [story["fixed_region"]] if story["fixed_region"] else []
        for region, domains in publisher_regions.items():
            if region not in regions and on_domain(host, domains):
                regions.append(region)
        for region, places in settings["regions"].items():
            if region not in regions and find_matches(text, places):
                regions.append(region)
        story["regions"] = regions

    # Newest first; stories without a date go to the bottom
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    kept.sort(key=lambda s: s["published"] or oldest, reverse=True)

    if SHOW_REMOVED_PUBLISHERS:
        print("\nTop publishers removed as not Australian:")
        for name, count in removed_publishers.most_common(30):
            print(f"  {count:4}  {name}")

    return kept[:settings["site"]["max_items"]], removed


# ---------- Part 3: story history ----------

def load_history():
    """Load stories saved by earlier runs (empty list on the first run)."""
    if not HISTORY_FILE.exists():
        return []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        stories = json.load(f)
    for story in stories:
        if story["published"]:
            story["published"] = datetime.fromisoformat(story["published"])
    return stories


def save_history(stories):
    """Save stories to the history file, safely replacing the old one."""
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    data = []
    for story in stories:
        item = dict(story)
        item["published"] = story["published"].isoformat() if story["published"] else None
        data.append(item)

    # Write to a temporary file first so a crash can't leave a broken file
    temp_file = HISTORY_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    temp_file.replace(HISTORY_FILE)


# ---------- Part 4: export data for the web page ----------

def export_site(stories, settings):
    """Write the slimmed-down story list that docs/index.html displays."""
    SITE_DIR.mkdir(exist_ok=True)

    items = []
    for story in stories:
        summary = story["summary"]
        # Google News summaries just repeat the headline, so drop those
        if title_key(summary).startswith(title_key(story["title"])):
            summary = ""
        items.append({
            "title": story["title"],
            "link": story["link"],
            "summary": summary,
            "published": story["published"].isoformat() if story["published"] else None,
            "source": story["source"],
            "tags": story["tags"],
            "regions": story["regions"],
        })

    data = {
        "title": settings["site"]["title"],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "groups": [{"name": name, "tags": list(tags)}
                   for name, tags in settings["tag_groups"].items()],
        "regions": list(settings["regions"]),
        "stories": items,
    }
    (SITE_DIR / "stories.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Tells GitHub Pages to serve the files as they are
    (SITE_DIR / ".nojekyll").touch()


# ---------- Run ----------

def main():
    settings = load_settings()

    history = load_history()
    old_links = {s["link"] for s in history}
    print(f"History: {len(history)} saved stories\n")

    feeds = settings["feeds"] + google_news_feeds(settings)
    fetched = []
    for feed in feeds:
        stories = fetch_feed(feed)
        print(f"{feed['name']}: {len(stories)} stories")
        fetched.extend(stories)
    print(f"\nFetched: {len(fetched)} stories")

    # History goes first so saved stories are kept over new duplicates
    kept, removed = process_stories(history + fetched, settings)
    new_count = sum(1 for s in kept if s["link"] not in old_links)

    save_history(kept)
    export_site(kept, settings)
    print(f"Saved: {len(kept)} stories ({new_count} new)")
    for reason, count in removed.most_common():
        print(f"  Removed ({reason}): {count}")

    # Counts help spot tags or regions that match too much or too little
    tag_counts = Counter(t for s in kept for t in s["tags"])
    region_counts = Counter(r for s in kept for r in s["regions"])
    print("\nTags:", ", ".join(f"{t} {n}" for t, n in tag_counts.most_common()))
    print("Regions:", ", ".join(f"{r} {n}" for r, n in region_counts.most_common()))
    print(f"No tags: {sum(1 for s in kept if not s['tags'])} stories")


if __name__ == "__main__":
    main()
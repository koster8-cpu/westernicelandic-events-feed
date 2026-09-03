#!/usr/bin/env python3
"""Build one ten-item RSS feed from Western Icelandic news/event sources."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import dateparser
import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "WesternIcelandicEventsFeed/1.0 (+https://github.com/koster8-cpu/westernicelandic-events-feed)"}
TIMEOUT = 25
MAX_ITEMS = 10


@dataclass(frozen=True)
class Item:
    title: str
    link: str
    date: datetime
    description: str
    source: str


def parsed_date(value: object) -> datetime | None:
    if not value:
        return None
    dt = dateparser.parse(str(value), settings={"RETURN_AS_TIMEZONE_AWARE": True, "TO_TIMEZONE": "UTC"})
    if not dt:
        return None
    return dt.astimezone(timezone.utc)


def clean(value: object, limit: int = 600) -> str:
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:limit]


def allowed(text: str, keywords: list[str]) -> bool:
    return not keywords or any(word.casefold() in text.casefold() for word in keywords)


def feed_candidates(page_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found = [urljoin(page_url, x.get("href", "")) for x in soup.select('link[rel~="alternate"]')
             if "rss" in x.get("type", "").lower() or "atom" in x.get("type", "").lower()]
    base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    return list(dict.fromkeys(found + [urljoin(page_url, "feed/"), base + "/feed/", base + "/rss.xml"]))


def from_feed(url: str, source: dict, seen_feeds: set[str]) -> list[Item]:
    if url in seen_feeds:
        return []
    seen_feeds.add(url)
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception:
        return []
    if not parsed.entries:
        return []
    items: list[Item] = []
    for entry in parsed.entries[:30]:
        title = clean(entry.get("title"), 220)
        link = entry.get("link") or url
        description = clean(entry.get("summary") or entry.get("description"))
        date = parsed_date(entry.get("published") or entry.get("updated") or entry.get("date"))
        combined = f"{title} {description} {link}"
        if title and date and allowed(combined, source["keywords"]):
            items.append(Item(title, link, date, description, source["name"]))
    return items


def jsonld_objects(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        if "@graph" in value:
            yield from jsonld_objects(value["@graph"])
        yield value
    elif isinstance(value, list):
        for part in value:
            yield from jsonld_objects(part)


def from_page(source: dict, html: str) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for obj in jsonld_objects(data):
            kind = obj.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]
            if not set(kinds) & {"Event", "NewsArticle", "Article", "BlogPosting"}:
                continue
            title = clean(obj.get("name") or obj.get("headline"), 220)
            link = obj.get("url") or source["url"]
            description = clean(obj.get("description"))
            date = parsed_date(obj.get("datePublished") or obj.get("startDate") or obj.get("dateModified"))
            combined = f"{title} {description} {link}"
            if title and date and allowed(combined, source["keywords"]):
                items.append(Item(title, urljoin(source["url"], link), date, description, source["name"]))
    return items


def collect(source: dict, seen_feeds: set[str]) -> list[Item]:
    try:
        response = requests.get(source["url"], headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        print(f"WARN {source['name']}: {exc}")
        return []
    page_items = from_page(source, response.text)
    feed_items: list[Item] = []
    for candidate in feed_candidates(source["url"], response.text):
        feed_items.extend(from_feed(candidate, source, seen_feeds))
    result = feed_items or page_items
    print(f"{source['name']}: {len(result)} item(s)")
    return result


def canonical(link: str) -> str:
    parsed = urlparse(link)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def write_rss(items: list[Item]) -> None:
    now = datetime.now(timezone.utc)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for tag, text in (
        ("title", "Western Icelandic news and events"),
        ("link", "https://github.com/koster8-cpu/westernicelandic-events-feed"),
        ("description", "The latest news and events from Icelandic organizations in North America and selected Icelandic cultural sources."),
        ("language", "en-ca"),
        ("lastBuildDate", format_datetime(now)),
    ):
        ET.SubElement(channel, tag).text = text
    for entry in items[:MAX_ITEMS]:
        node = ET.SubElement(channel, "item")
        ET.SubElement(node, "title").text = f"{entry.title} — {entry.source}"
        ET.SubElement(node, "link").text = entry.link
        ET.SubElement(node, "guid", isPermaLink="false").text = hashlib.sha256(entry.link.encode()).hexdigest()
        ET.SubElement(node, "pubDate").text = format_datetime(entry.date)
        ET.SubElement(node, "source", url=entry.link).text = entry.source
        ET.SubElement(node, "description").text = entry.description or f"From {entry.source}"
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(ROOT / "feed.xml", encoding="utf-8", xml_declaration=True)


def main() -> None:
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    seen_feeds: set[str] = set()
    gathered = [item for source in sources for item in collect(source, seen_feeds)]
    unique: dict[str, Item] = {}
    for item in gathered:
        key = canonical(item.link)
        if key not in unique or item.date > unique[key].date:
            unique[key] = item
    ordered = sorted(unique.values(), key=lambda item: item.date, reverse=True)
    write_rss(ordered[:MAX_ITEMS])
    print(f"Wrote {min(len(ordered), MAX_ITEMS)} item(s) to feed.xml")


if __name__ == "__main__":
    main()

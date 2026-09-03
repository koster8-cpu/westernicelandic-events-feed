# Western Icelandic news and events feed

This repository combines 15 Icelandic community, cultural, literary, and music sources into one RSS 2.0 feed. Items are deduplicated, sorted newest first by their supplied publication/event date, and limited to the latest 10.

## Feed address

`https://raw.githubusercontent.com/koster8-cpu/westernicelandic-events-feed/main/feed.xml`

The GitHub Actions workflow refreshes the feed every six hours. It can also be run manually from **Actions → Update RSS feed → Run workflow**.

## How it works

The generator uses a source's native RSS/Atom feed when one is discoverable and otherwise reads Event, NewsArticle, Article, or BlogPosting structured data from the source page. Broad sources such as Iceland Music, Scandinavia House, and Nordic Northwest are filtered for relevant Icelandic or North American terms.

If one source changes its website, the other sources continue updating. The workflow log identifies any source that could not be reached.

## Files

- `sources.json`: source names, pages, and optional filters
- `generate_feed.py`: feed discovery, extraction, filtering, sorting, and RSS output
- `feed.xml`: public combined feed
- `.github/workflows/update-feed.yml`: automatic six-hour refresh

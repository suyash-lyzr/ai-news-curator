#!/usr/bin/env python3
"""Local AI news dashboard. Serves public RSS feeds with a saved fallback."""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import socket
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "static" / "index.html"
FONT_DIR = ROOT / "static" / "fonts"
CACHE_PATH = ROOT / ".cache" / "news.json"

USER_AGENT = "AINewsCurator/1.0 (local dashboard)"
MAX_BYTES = 2_000_000
FETCH_TIMEOUT = 8
CACHE_TTL = timedelta(minutes=10)
CACHE_VERSION = 1
PER_SOURCE = 5
STORE_LIMIT = 8
CATEGORY_CAP = 8
MAX_AGE = timedelta(days=14)
FALLBACK_AGE = timedelta(days=40)
SUMMARY_STORE = 800
SUMMARY_CLIP = 220
LEAD_CLIP = 340

FEEDS = [
    {
        "id": "arxiv-ai",
        "name": "arXiv cs.AI",
        "home": "https://arxiv.org/list/cs.AI/recent",
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "category": "research",
    },
    {
        "id": "deepmind",
        "name": "Google DeepMind",
        "home": "https://deepmind.google/discover/blog/",
        "url": "https://deepmind.google/blog/rss.xml",
        "category": "research",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "home": "https://openai.com/news",
        "url": "https://openai.com/news/rss.xml",
        "category": "products",
    },
    {
        "id": "google-ai",
        "name": "Google",
        "home": "https://blog.google/technology/ai/",
        "url": "https://blog.google/technology/ai/rss/",
        "category": "products",
    },
    {
        "id": "techcrunch",
        "name": "TechCrunch",
        "home": "https://techcrunch.com/category/artificial-intelligence/",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "category": "industry",
    },
    {
        "id": "verge",
        "name": "The Verge",
        "home": "https://www.theverge.com/ai-artificial-intelligence",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "category": "industry",
    },
    {
        "id": "mit",
        "name": "MIT Technology Review",
        "home": "https://www.technologyreview.com/topic/artificial-intelligence/",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "category": "industry",
    },
    {
        "id": "ars",
        "name": "Ars Technica",
        "home": "https://arstechnica.com/ai/",
        "url": "https://arstechnica.com/ai/feed/",
        "category": "industry",
    },
    {
        "id": "wired",
        "name": "Wired",
        "home": "https://www.wired.com/tag/ai/",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "category": "industry",
    },
]

FEEDS_BY_ID = {feed["id"]: feed for feed in FEEDS}

CATEGORIES = [
    ("research", "Research", "Papers and lab posts"),
    ("products", "Products", "Launches and company news"),
    ("industry", "Industry", "Reporting from the press"),
]

FONTS = {
    "newsreader-400.woff2",
    "newsreader-400i.woff2",
    "newsreader-600.woff2",
    "figtree-500.woff2",
    "figtree-600.woff2",
}

_LOCK = threading.Lock()


class FetchError(Exception):
    pass


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def clean_summary(summary: str, title: str) -> str:
    summary = re.sub(
        r"^arXiv:\S+\s+Announce Type:\s*\w+\s+Abstract:\s*",
        "",
        summary,
        flags=re.I,
    )
    if title and summary.lower().startswith(title.lower()):
        summary = summary[len(title) :].lstrip(" -:—|")
    summary = re.sub(
        r"\s*(The post .+ appeared first on .+|Continue reading\.{0,3}|Read more\.{0,3})$",
        "",
        summary,
        flags=re.I,
    )
    return summary.strip()


def clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    if len(cut) < limit * 0.6:
        cut = text[:limit].rstrip()
    return cut.rstrip(".,;: ") + "…"


def parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonicalize(href: str) -> str | None:
    parts = urllib.parse.urlsplit((href or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", urllib.parse.urlencode(query), "")
    )


def pick_link(links: list[tuple[str, str]]) -> str | None:
    ordered = [href for rel, href in links if rel in ("alternate", "")]
    ordered.extend(href for rel, href in links if rel not in ("alternate", ""))
    for href in ordered:
        url = canonicalize(href)
        if url:
            return url
    return None


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        if local_name(el.tag) not in ("item", "entry"):
            continue
        title = ""
        summary = ""
        content = ""
        links: list[tuple[str, str]] = []
        published = None
        for child in list(el):
            name = local_name(child.tag)
            if name == "title" and not title:
                title = clean_text("".join(child.itertext()))
            elif name == "link":
                href = (child.text or "").strip() or child.attrib.get("href", "")
                rel = child.attrib.get("rel", "alternate")
                if href:
                    links.append((rel, href.strip()))
            elif name in ("description", "summary"):
                text = clean_text("".join(child.itertext()))
                if len(text) > len(summary):
                    summary = text
            elif name in ("encoded", "content") and not content:
                content = clean_text("".join(child.itertext()))
            elif name in ("pubDate", "published", "updated", "date") and published is None:
                published = parse_date("".join(child.itertext()))
        if not summary:
            summary = content
        title = title.strip()
        url = pick_link(links)
        if len(title) < 2 or not url:
            continue
        summary = clean_summary(summary, title)
        items.append(
            {
                "title": title,
                "url": url,
                "summary": clip(summary, SUMMARY_STORE) if summary else "",
                "published": published.isoformat() if published else None,
            }
        )
    return items


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def trim_items(items: list[dict], source_id: str) -> list[dict]:
    dated = []
    undated = []
    for item in items:
        item = dict(item)
        item["source_id"] = source_id
        dt = parse_iso(item.get("published"))
        if dt is None:
            undated.append(item)
        else:
            dated.append((dt, item))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    chosen = [item for _, item in dated[:STORE_LIMIT]]
    if not chosen:
        chosen = undated[:STORE_LIMIT]
    return chosen


def norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "being", "between", "can", "could", "does", "each", "from", "have", "into",
    "its", "just", "more", "most", "much", "new", "now", "only", "over", "than",
    "that", "the", "their", "them", "then", "there", "these", "this", "those",
    "through", "using", "what", "when", "where", "which", "while", "with", "your",
    "will", "would", "you",
}


def title_tokens(title: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", title.lower()) if len(word) > 3 and word not in STOPWORDS}


def same_story(title: str, previous: set[str]) -> bool:
    tokens = title_tokens(title)
    if len(tokens) < 4 or len(previous) < 4:
        return False
    shared = tokens & previous
    return len(shared) >= 4 and len(shared) / min(len(tokens), len(previous)) >= 0.7


def within(dt: datetime, now: datetime, window: timedelta) -> bool:
    return timedelta(hours=-36) <= (now - dt) <= window


def pools_for(digest: dict, now: datetime) -> dict[str, list[tuple[str, list[dict]]]]:
    """Newest stories per category, deduped, with one outlet unable to fill the page."""
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    seen_tokens: list[set[str]] = []
    grouped: dict[str, list[tuple[str, list[dict]]]] = {key: [] for key, _, _ in CATEGORIES}
    sources = digest.get("sources") or {}
    for feed in FEEDS:
        saved = sources.get(feed["id"]) or {}
        raw_items = saved.get("items") or []
        dated = []
        undated = []
        for item in raw_items:
            if item.get("source_id") != feed["id"]:
                continue
            dt = parse_iso(item.get("published"))
            if dt is None:
                undated.append(item)
            else:
                dated.append((dt, item))
        dated.sort(key=lambda pair: pair[0], reverse=True)
        recent = [item for dt, item in dated if within(dt, now, MAX_AGE)]
        chosen = recent[:PER_SOURCE]
        if not chosen:
            chosen = [item for dt, item in dated if within(dt, now, FALLBACK_AGE)][:2]
        if not chosen and not dated:
            chosen = undated[:PER_SOURCE]
        kept = []
        for item in chosen:
            title = item.get("title") or ""
            title_key = norm_title(title)
            url = item.get("url") or ""
            tokens = title_tokens(title)
            if (
                not title_key
                or not url
                or title_key in seen_titles
                or url in seen_urls
                or any(same_story(title, previous) for previous in seen_tokens)
            ):
                continue
            seen_titles.add(title_key)
            seen_urls.add(url)
            if tokens:
                seen_tokens.append(tokens)
            kept.append(item)
        if kept:
            grouped[feed["category"]].append((feed["id"], kept))
    return grouped


def select_category(pools: list[tuple[str, list[dict]]], cap: int = CATEGORY_CAP) -> list[dict]:
    candidates = [item for _, items in pools for item in items]
    if not candidates:
        return []
    earliest = datetime.min.replace(tzinfo=timezone.utc)

    def stamp(item: dict) -> datetime:
        return parse_iso(item.get("published")) or earliest

    lead = max(candidates, key=stamp)
    remaining = []
    lead_index = 0
    for sid, items in pools:
        kept = [item for item in items if item is not lead]
        if any(item is lead for item in items):
            lead_index = len(remaining)
        remaining.append((sid, kept))
    if len(remaining) > 1:
        remaining = remaining[lead_index + 1 :] + remaining[: lead_index + 1]
    picked = [lead]
    while len(picked) < cap:
        moved = False
        for _, items in remaining:
            if items and len(picked) < cap:
                picked.append(items.pop(0))
                moved = True
        if not moved:
            break
    return picked


def relative_time(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return ""
    seconds = int((now - dt).total_seconds())
    if seconds < 90:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days}d ago"
    return f"{dt.day} {dt.strftime('%b')}"


def exact_time(dt: datetime) -> str:
    return f"{dt.day} {dt.strftime('%b %Y')}, {dt.strftime('%H:%M')} UTC"


def long_date(dt: datetime) -> str:
    return f"{dt.strftime('%A')}, {dt.day} {dt.strftime('%B %Y')}"


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def render_card(item: dict, now: datetime, lead: bool) -> str:
    feed = FEEDS_BY_ID[item["source_id"]]
    published = parse_iso(item.get("published"))
    when = relative_time(published, now)
    time_html = ""
    if published is not None and when:
        time_html = (
            f'<time datetime="{esc(published.isoformat())}" title="{esc(exact_time(published))}">'
            f"{esc(when)}</time>"
        )
    summary = item.get("summary") or ""
    summary_html = ""
    if summary:
        summary_html = f'<p class="summary">{esc(clip(summary, LEAD_CLIP if lead else SUMMARY_CLIP))}</p>'
    css = "card lead" if lead else "card"
    url = esc(item["url"])
    return (
        f'<article class="{css}" data-category="{esc(feed["category"])}">'
        f'<p class="meta"><a class="source" href="{esc(feed["home"])}" target="_blank" rel="noopener noreferrer">{esc(feed["name"])}</a>'
        f"{time_html}</p>"
        f'<h3><a href="{url}" target="_blank" rel="noopener noreferrer">{esc(item["title"])}</a></h3>'
        f"{summary_html}"
        f'<a class="origin" href="{url}" target="_blank" rel="noopener noreferrer">Original story</a>'
        f"</article>"
    )


def render_sections(digest: dict, now: datetime) -> tuple[str, str, int]:
    grouped = pools_for(digest, now)
    jumps = []
    sections = []
    total = 0
    for key, label, blurb in CATEGORIES:
        stories = select_category(grouped.get(key) or [])
        if not stories:
            continue
        total += len(stories)
        jumps.append(
            f'<a href="#{esc(key)}"><span class="swatch {esc(key)}" aria-hidden="true"></span>'
            f"{esc(label)} <em>{len(stories)}</em></a>"
        )
        cards = "".join(render_card(item, now, index == 0) for index, item in enumerate(stories))
        sections.append(
            f'<section class="section" id="{esc(key)}">'
            f'<div class="section-head"><h2>'
            f'<span class="swatch {esc(key)}" aria-hidden="true"></span>{esc(label)}</h2>'
            f"<p>{esc(blurb)}</p></div>"
            f'<div class="grid">{cards}</div></section>'
        )
    if not sections:
        sections.append(
            '<div class="empty"><h2>No stories yet</h2>'
            "<p>The feeds did not respond, and there is no saved briefing on this machine.</p>"
            '<a class="refresh" href="/?fresh=1">Try again</a></div>'
        )
    jump_html = f'<nav class="jumps">{"".join(jumps)}</nav>' if jumps else ""
    return jump_html, "".join(sections), total


def source_failures(digest: dict) -> list[tuple[str, str, bool]]:
    failures = []
    sources = digest.get("sources") or {}
    for feed in FEEDS:
        saved = sources.get(feed["id"]) or {}
        if saved.get("ok", True) and not saved.get("error"):
            continue
        if "items" not in saved and "error" not in saved:
            continue
        failures.append((feed["name"], saved.get("error") or "unavailable", bool(saved.get("items"))))
    return failures


def render_banner(digest: dict) -> str:
    failures = source_failures(digest)
    if not failures:
        return ""
    parts = []
    for name, error, has_saved in failures:
        if has_saved:
            parts.append(f"{name} ({error}; showing saved stories)")
        else:
            parts.append(f"{name} ({error})")
    return f'<p class="banner" role="status">Some feeds did not respond: {esc("; ".join(parts))}.</p>'


def render_footer() -> str:
    links = ", ".join(
        f'<a href="{esc(feed["home"])}" target="_blank" rel="noopener noreferrer">{esc(feed["name"])}</a>'
        for feed in FEEDS
    )
    return (
        f"<p>Sources: {links}.</p>"
        '<p class="fine">Stories are cached on this machine. If a feed fails, its last saved '
        "stories stay on the page.</p>"
        '<p class="fine">Anthropic, Meta AI, and VentureBeat are in the curator’s source notes '
        "but are not shown here. They did not offer a working public feed when this page was built.</p>"
    )


def render_dateblock(digest: dict, now: datetime, total: int) -> str:
    saved = parse_iso(digest.get("saved_at")) or now
    count = f"{total} {'story' if total == 1 else 'stories'}" if total else "No stories loaded"
    return (
        f'<p class="day">{esc(long_date(now))}</p>'
        f'<p class="updated">{esc(count)} · updated {esc(saved.strftime("%H:%M"))} UTC</p>'
        '<a class="refresh" href="/?fresh=1">Refresh feeds</a>'
    )


def build_page(digest: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    jumps, sections, total = render_sections(digest, now)
    return (
        template.replace("<!--DATEBLOCK-->", render_dateblock(digest, now, total))
        .replace("<!--JUMPS-->", jumps)
        .replace("<!--BANNER-->", render_banner(digest))
        .replace("<!--SECTIONS-->", sections)
        .replace("<!--FOOTER-->", render_footer())
    )


def public_digest(digest: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    grouped = pools_for(digest, now)
    categories = []
    for key, label, blurb in CATEGORIES:
        stories = []
        for item in select_category(grouped.get(key) or []):
            feed = FEEDS_BY_ID[item["source_id"]]
            published = parse_iso(item.get("published"))
            stories.append(
                {
                    "title": item["title"],
                    "url": item["url"],
                    "summary": clip(item.get("summary") or "", SUMMARY_CLIP),
                    "source": feed["name"],
                    "source_url": feed["home"],
                    "category": key,
                    "published": item.get("published"),
                    "time": relative_time(published, now),
                }
            )
        if stories:
            categories.append({"id": key, "label": label, "blurb": blurb, "stories": stories})
    return {
        "updated": digest.get("saved_at"),
        "categories": categories,
        "feeds": [
            {
                "id": feed["id"],
                "name": feed["name"],
                "category": feed["category"],
                "ok": bool((digest.get("sources") or {}).get(feed["id"], {}).get("ok", False)),
                "error": (digest.get("sources") or {}).get(feed["id"], {}).get("error"),
            }
            for feed in FEEDS
        ],
    }


def read_limited(response, limit: int = MAX_BYTES) -> bytes:
    chunks = []
    total = 0
    while True:
        block = response.read(65536)
        if not block:
            break
        total += len(block)
        if total > limit:
            raise FetchError("feed too large")
        chunks.append(block)
    return b"".join(chunks)


def maybe_decompress(raw: bytes, headers: dict) -> bytes:
    encoding = (headers.get("Content-Encoding") or "").lower()
    if raw[:2] == b"\x1f\x8b" or "gzip" in encoding:
        try:
            return gzip.decompress(raw)
        except gzip.BadGzipFile as exc:
            raise FetchError("could not read feed") from exc
    return raw


def fetch_url(url: str, timeout: int = FETCH_TIMEOUT) -> tuple[bytes, dict]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return read_limited(response), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
            raise FetchError("timed out") from exc
        raise FetchError("connection failed") from exc


def fetch_feed(feed: dict, fetch=fetch_url) -> list[dict]:
    raw, headers = fetch(feed["url"])
    try:
        items = parse_feed(maybe_decompress(raw, headers))
    except ET.ParseError as exc:
        raise FetchError("could not read feed") from exc
    items = trim_items(items, feed["id"])
    if not items:
        raise FetchError("feed returned no stories")
    return items


def empty_digest(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {"version": CACHE_VERSION, "saved_at": now.isoformat(), "sources": {}}


def refresh(previous: dict | None, fetch=fetch_url, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    previous_sources = (previous or {}).get("sources") or {}
    sources: dict[str, dict] = {}

    def one(feed: dict) -> tuple[str, dict]:
        try:
            items = fetch_feed(feed, fetch)
        except FetchError as exc:
            message = str(exc)
        except Exception:
            traceback.print_exc()
            message = "could not read feed"
        else:
            print(f"[feed] {feed['name']}: {len(items)} stories", file=sys.stderr)
            return feed["id"], {
                "ok": True,
                "error": None,
                "fetched_at": now.isoformat(),
                "items": items,
            }
        prior = previous_sources.get(feed["id"]) or {}
        print(f"[feed] {feed['name']}: {message}", file=sys.stderr)
        return feed["id"], {
            "ok": False,
            "error": message,
            "fetched_at": prior.get("fetched_at"),
            "items": prior.get("items") or [],
        }

    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        for source_id, payload in pool.map(one, FEEDS):
            sources[source_id] = payload
    return {"version": CACHE_VERSION, "saved_at": now.isoformat(), "sources": sources}


def load_cache() -> dict | None:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    return data


def save_cache(digest: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(digest), encoding="utf-8")
    temporary.replace(CACHE_PATH)


def cache_is_fresh(digest: dict | None, now: datetime) -> bool:
    if not digest or not digest.get("sources"):
        return False
    saved = parse_iso(digest.get("saved_at"))
    if saved is None:
        return False
    return now - saved <= CACHE_TTL


def get_digest(force: bool = False, fetch=fetch_url, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        cached = load_cache()
        if cached and not force and cache_is_fresh(cached, now):
            return cached
        digest = refresh(cached, fetch=fetch, now=now)
        try:
            save_cache(digest)
        except OSError as exc:
            print(f"[cache] could not save: {exc}", file=sys.stderr)
        return digest


class Handler(BaseHTTPRequestHandler):
    server_version = "AINewsDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        try:
            self.route()
        except Exception:
            traceback.print_exc()
            self.send_bytes(500, b"The briefing could not be loaded.", "text/plain; charset=utf-8")

    def route(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            force = urllib.parse.parse_qs(parsed.query).get("fresh", ["0"])[0] == "1"
            digest = get_digest(force=force)
            page = build_page(digest).encode("utf-8")
            self.send_bytes(200, page, "text/html; charset=utf-8")
            return
        if path == "/api/news":
            force = urllib.parse.parse_qs(parsed.query).get("fresh", ["0"])[0] == "1"
            body = json.dumps(public_digest(get_digest(force=force))).encode("utf-8")
            self.send_bytes(200, body, "application/json; charset=utf-8")
            return
        if path.startswith("/fonts/"):
            name = path.removeprefix("/fonts/")
            if name not in FONTS or "/" in name or ".." in name:
                self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")
                return
            font = (FONT_DIR / name).resolve()
            if font.parent != FONT_DIR.resolve() or not font.is_file():
                self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")
                return
            self.send_bytes(200, font.read_bytes(), "font/woff2", cache=True)
            return
        self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")

    def send_bytes(self, code: int, body: bytes, content_type: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if cache:
            self.send_header("Cache-Control", "public, max-age=604800")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the AI news dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    print("Fetching feeds…", file=sys.stderr)
    get_digest(force=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"AI news dashboard at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

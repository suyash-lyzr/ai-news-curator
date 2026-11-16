"""Parser, grouping, and page tests. No network."""

import gzip
import unittest
from datetime import datetime, timedelta, timezone

import server


NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def item(title, url, source_id, hours_ago=1, summary="A short summary of the story."):
    published = (NOW - timedelta(hours=hours_ago)).isoformat()
    return {
        "title": title,
        "url": url,
        "summary": summary,
        "published": published,
        "source_id": source_id,
    }


RSS = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>When Should LLM Agents Forget?</title>
      <link>https://arxiv.org/abs/2611.17338?utm_source=rss</link>
      <description>arXiv:2611.17338v1 Announce Type: new Abstract: Memory filters can drop query-critical facts.</description>
      <pubDate>Mon, 16 Nov 2026 00:00:00 -0500</pubDate>
    </item>
    <item>
      <title>&lt;script&gt;alert(1)&lt;/script&gt;</title>
      <link>javascript:alert(1)</link>
      <description>Ignore me</description>
    </item>
    <item>
      <title>Hello &lt;b&gt;world&lt;/b&gt;</title>
      <link>https://example.com/hello</link>
      <description>&lt;img src=x onerror=alert(1)&gt;Plain summary. Continue reading.</description>
      <pubDate>Mon, 16 Nov 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title type="html">Audible adds an AI synopsis</title>
    <link rel="alternate" type="text/html" href="https://www.theverge.com/story"/>
    <updated>2026-11-16T07:52:05-05:00</updated>
    <summary type="html">Audible is introducing an &lt;em&gt;AI-assisted&lt;/em&gt; synopsis.</summary>
    <content type="html">Full article should not replace the summary.</content>
  </entry>
</feed>
"""


class ParseTests(unittest.TestCase):
    def test_rss_strips_markup_and_rejects_javascript(self):
        items = server.parse_feed(RSS)
        self.assertEqual(len(items), 2)
        paper, hello = items
        self.assertEqual(paper["title"], "When Should LLM Agents Forget?")
        self.assertEqual(paper["url"], "https://arxiv.org/abs/2611.17338")
        self.assertTrue(paper["summary"].startswith("Memory filters"))
        self.assertEqual(hello["title"], "Hello world")
        self.assertEqual(hello["summary"], "Plain summary.")
        self.assertNotIn("onerror", hello["summary"])

    def test_atom_prefers_summary_and_alternate_link(self):
        items = server.parse_feed(ATOM)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.theverge.com/story")
        self.assertIn("AI-assisted", items[0]["summary"])
        self.assertNotIn("Full article", items[0]["summary"])

    def test_gzip_magic_is_decompressed(self):
        raw = gzip.compress(RSS)
        xml_bytes = server.maybe_decompress(raw, {})
        self.assertIn(b"When Should LLM Agents Forget?", xml_bytes)

    def test_dates_become_utc(self):
        published = server.parse_date("Mon, 16 Nov 2026 09:00:00 GMT")
        self.assertEqual(published, datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc))
        iso = server.parse_date("2026-11-16T07:52:05-05:00")
        self.assertEqual(iso, datetime(2026, 11, 16, 12, 52, 5, tzinfo=timezone.utc))


class GroupTests(unittest.TestCase):
    def test_round_robin_does_not_let_one_feed_fill_the_section(self):
        digest = {
            "sources": {
                "arxiv-ai": {
                    "items": [
                        item(f"Paper {n}", f"https://arxiv.org/abs/{n}", "arxiv-ai", hours_ago=n)
                        for n in range(1, 6)
                    ]
                },
                "deepmind": {
                    "items": [
                        item("Gemini update", "https://deepmind.google/blog/gemini", "deepmind", hours_ago=30)
                    ]
                },
            }
        }
        pools = server.pools_for(digest, NOW)
        stories = server.select_category(pools["research"])
        sources = [story["source_id"] for story in stories]
        self.assertEqual(sources[0], "arxiv-ai")
        self.assertEqual(sources[1], "deepmind")
        self.assertIn("deepmind", sources)

    def test_similar_headlines_collapse_to_one_story(self):
        digest = {
            "sources": {
                "techcrunch": {
                    "items": [
                        item(
                            "Google Maps can now build trip itineraries with real-time details about each stop",
                            "https://techcrunch.com/maps",
                            "techcrunch",
                            hours_ago=1,
                        )
                    ]
                },
                "verge": {
                    "items": [
                        item(
                            "Google Maps can now create trip itineraries for you",
                            "https://www.theverge.com/maps",
                            "verge",
                            hours_ago=2,
                        ),
                        item(
                            "Audible is trying to make it easier to find audiobooks",
                            "https://www.theverge.com/audible",
                            "verge",
                            hours_ago=3,
                        ),
                    ]
                },
            }
        }
        stories = server.select_category(server.pools_for(digest, NOW)["industry"])
        titles = [story["title"] for story in stories]
        self.assertEqual(len(titles), 2)
        self.assertIn("Google Maps can now build trip itineraries with real-time details about each stop", titles)
        self.assertIn("Audible is trying to make it easier to find audiobooks", titles)

    def test_duplicate_titles_keep_the_earlier_source(self):
        digest = {
            "sources": {
                "techcrunch": {
                    "items": [item("Same headline", "https://techcrunch.com/a", "techcrunch", hours_ago=2)]
                },
                "verge": {
                    "items": [item("Same headline", "https://www.theverge.com/a", "verge", hours_ago=1)]
                },
            }
        }
        pools = server.pools_for(digest, NOW)
        stories = server.select_category(pools["industry"])
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_id"], "techcrunch")

    def test_failed_fetch_keeps_saved_stories(self):
        previous = {
            "sources": {
                "openai": {
                    "ok": True,
                    "fetched_at": "2026-11-16T12:00:00+00:00",
                    "items": [item("Saved launch", "https://openai.com/index/saved", "openai")],
                }
            }
        }

        def fetch(url, timeout=8):
            if "openai.com" in url:
                raise server.FetchError("timed out")
            if "deepmind" in url:
                payload = gzip.compress(
                    b"""<?xml version="1.0"?><rss><channel><item>
                    <title>Lab note</title><link>https://deepmind.google/blog/note</link>
                    <description>A lab note.</description>
                    <pubDate>Mon, 16 Nov 2026 12:00:00 GMT</pubDate>
                    </item></channel></rss>"""
                )
                return payload, {"Content-Encoding": "gzip"}
            raise server.FetchError("HTTP 404")

        digest = server.refresh(previous, fetch=fetch, now=NOW)
        openai = digest["sources"]["openai"]
        self.assertFalse(openai["ok"])
        self.assertEqual(openai["error"], "timed out")
        self.assertEqual(openai["items"][0]["title"], "Saved launch")
        self.assertTrue(digest["sources"]["deepmind"]["ok"])
        self.assertEqual(digest["sources"]["deepmind"]["items"][0]["title"], "Lab note")
        self.assertFalse(digest["sources"]["wired"]["ok"])
        self.assertEqual(digest["sources"]["wired"]["items"], [])


class PageTests(unittest.TestCase):
    def test_page_renders_real_fields_and_escapes(self):
        digest = {
            "saved_at": NOW.isoformat(),
            "sources": {
                "openai": {
                    "ok": True,
                    "items": [
                        item(
                            "Partnership <script>",
                            "https://openai.com/index/deal",
                            "openai",
                            summary="A partnership announced today.",
                        )
                    ],
                }
            },
        }
        page = server.build_page(digest, NOW)
        self.assertIn("Today in", page)
        self.assertIn("Partnership &lt;script&gt;", page)
        self.assertIn("https://openai.com/index/deal", page)
        self.assertIn("Original story", page)
        self.assertIn("OpenAI", page)
        self.assertIn('id="products"', page)
        self.assertNotIn("<script>", page.split("<main", 1)[1])

    def test_empty_digest_still_renders(self):
        page = server.build_page(server.empty_digest(NOW), NOW)
        self.assertIn("No stories yet", page)
        self.assertIn("Today in", page)
        self.assertIn("Refresh feeds", page)

    def test_banner_names_a_failed_feed(self):
        digest = server.empty_digest(NOW)
        digest["sources"] = {"wired": {"ok": False, "error": "timed out", "items": []}}
        page = server.build_page(digest, NOW)
        self.assertIn("Wired", page)
        self.assertIn("timed out", page)


if __name__ == "__main__":
    unittest.main()

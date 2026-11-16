# AI news dashboard

A local page of recent AI stories. It reads public RSS feeds, groups them into research, products, and industry, and still renders if a feed fails.

From the repository root:

```bash
python3 dashboard/server.py
```

Then open http://127.0.0.1:8787

Python 3.11 or newer is enough. The standard library does the fetching, parsing, and serving. There is no install step, no account, and no gitagent runtime.

Stories are saved in `dashboard/.cache/news.json` (not committed). A feed that fails keeps its last saved stories. Use **Refresh feeds** on the page, or open `/?fresh=1`, to fetch again before the 10-minute cache expires.

The outlets are the ones in `knowledge/ai-sources.md` that publish a working public feed: arXiv cs.AI, Google DeepMind, OpenAI, Google’s AI blog, TechCrunch, The Verge, MIT Technology Review, Ars Technica, and Wired.

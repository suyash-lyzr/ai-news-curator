# ai-news-curator

AI-powered news curator that fetches the latest AI news from the web and Twitter, then emails you a digest.

## Run

```bash
npx @open-gitagent/gitagent run -r https://github.com/suyash-lyzr/ai-news-curator
```

## What It Can Do

- **Fetch Web News** — Searches top tech publications, research blogs, and aggregators for the latest AI stories
- **Monitor Twitter/X** — Captures trending AI discussions, product announcements, and notable threads
- **Email Digest** — Compiles everything into a clean, categorized email digest and sends it to you via Gmail

## Example Prompts

```
"Get me today's AI news and email it to me"
"What's trending in AI on Twitter this week?"
"Send me a digest of AI research breakthroughs"
```

## Structure

```
ai-news-curator/
├── agent.yaml
├── SOUL.md
├── RULES.md
├── README.md
├── skills/
│   ├── fetch-news/
│   │   └── SKILL.md
│   ├── fetch-twitter/
│   │   └── SKILL.md
│   └── send-email-digest/
│       └── SKILL.md
├── tools/
│   ├── web-search.yaml
│   ├── twitter-search.yaml
│   └── email-send.yaml
├── knowledge/
│   ├── index.yaml
│   └── ai-sources.md
└── dashboard/
    ├── server.py
    └── static/
```

## Dashboard

A local browser briefing of recent AI stories from public RSS feeds. It does not use the gitagent runtime.

```bash
python3 dashboard/server.py
```

Then open http://127.0.0.1:8787. See `dashboard/README.md` for how caching works.

## Built with

[gitagent](https://github.com/open-gitagent/gitagent) — a git-native, framework-agnostic open standard for AI agents.

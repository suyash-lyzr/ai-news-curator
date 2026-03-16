---
name: fetch-news
description: Search the web for latest AI news from top tech publications, research sites, and aggregators
license: MIT
allowed-tools: WebSearch WebFetch Read
metadata:
  author: suyashmankar
  version: "1.0.0"
  category: research
---

# Fetch AI News from the Web

## When to Use
When the user wants to gather the latest AI news, research updates, or industry developments from the web.

## Instructions

1. Search for the latest AI news using web search with queries like:
   - "latest AI news today"
   - "AI research breakthroughs this week"
   - "AI industry news funding acquisitions"
   - "AI regulation policy news"

2. Target these high-quality sources:
   - **Research**: arXiv, Google AI Blog, OpenAI Blog, Meta AI, DeepMind
   - **Industry**: TechCrunch, The Verge, VentureBeat, Wired, Ars Technica
   - **Aggregators**: Hacker News, Reddit r/MachineLearning, AI News
   - **Analysis**: MIT Technology Review, The Information, Bloomberg

3. For each item, extract:
   - Headline
   - 1-2 sentence summary
   - Source URL
   - Publication date
   - Category: Research | Industry | Policy | Community

4. Deduplicate stories that appear across multiple sources — keep the best source.

5. Rank by a combination of recency and significance.

6. Return a structured list of 5-10 top stories ready for the digest.

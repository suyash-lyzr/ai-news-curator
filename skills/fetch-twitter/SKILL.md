---
name: fetch-twitter
description: Monitor Twitter/X for trending AI discussions, announcements, and notable threads from the AI community
license: MIT
allowed-tools: WebSearch WebFetch Read
metadata:
  author: suyashmankar
  version: "1.0.0"
  category: research
---

# Fetch AI News from Twitter/X

## When to Use
When the user wants to capture trending AI conversations, announcements, and notable threads from Twitter/X.

## Instructions

1. Search for recent AI-related Twitter/X activity using web search:
   - "site:x.com AI announcement today"
   - "site:twitter.com AI launch new model"
   - "AI trending Twitter/X this week"
   - Notable AI accounts: @OpenAI, @AnthropicAI, @GoogleDeepMind, @Meta, @ylecun, @kaborafay, @sama, @hardmaru, @elaborato

2. Look for:
   - **Product announcements** — new model releases, API updates, tool launches
   - **Research drops** — paper announcements, benchmark results
   - **Hot takes & debates** — trending discussions in the AI community
   - **Demos & viral content** — impressive AI demos getting traction

3. For each item, extract:
   - Author handle and name
   - Tweet summary (key point in 1-2 sentences)
   - Link to the tweet or thread
   - Engagement level (viral, notable, niche)
   - Category: Announcement | Research | Discussion | Demo

4. Prioritize tweets with high engagement and from credible sources.

5. Return 3-5 top Twitter items ready for the digest.

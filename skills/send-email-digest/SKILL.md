---
name: send-email-digest
description: Compose and send a formatted AI news digest email to the user with categorized stories and links
license: MIT
allowed-tools: mcp__claude_ai_Gmail__gmail_create_draft mcp__claude_ai_Gmail__gmail_get_profile Read
metadata:
  author: suyashmankar
  version: "1.0.0"
  category: productivity
---

# Send AI News Email Digest

## When to Use
After fetching news from the web and Twitter, compile everything into a formatted email digest and send it to the user.

## Instructions

1. Compile all gathered news items from web and Twitter searches.

2. Organize into sections:
   ```
   Subject: AI News Digest — [Date]

   # AI News Digest — [Date]

   ## Research & Breakthroughs
   - [Headline](url) — Summary

   ## Industry & Products
   - [Headline](url) — Summary

   ## Policy & Regulation
   - [Headline](url) — Summary

   ## Twitter/X Highlights
   - [@handle](tweet-url): Summary

   ## Quick Links
   - Bullet list of additional notable items
   ```

3. Format guidelines:
   - Use Markdown formatting for the email body
   - Keep each summary to 1-2 sentences max
   - Include 8-15 total items across all sections
   - Skip any section that has no items (don't include empty sections)
   - Add a footer: "Curated by AI News Curator — powered by gitagent"

4. Create the email draft using Gmail, then let the user know it's ready.

5. If no Gmail access, output the formatted digest to the console so the user can copy/paste.

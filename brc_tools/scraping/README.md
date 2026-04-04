# Web Scraping Tools

This directory contains tools for fetching content from social media platforms.

## Facebook Post Fetcher

Retrieves recent posts from public Facebook pages (default: aviation247).

### Quick Start

```bash
python get_aviation247_posts.py --count 5
```

Three methods are available, in order of preference:

---

### 1. Apify (Recommended)

Works for **any public page** -- you do not need to manage the page.

#### Setup (~2 minutes)

1. Sign up at <https://apify.com> (free, no credit card)
2. Go to **Settings -> Integrations** and copy your API token
3. Set environment variable:
   ```bash
   export APIFY_API_TOKEN='your_token_here'
   ```

#### Usage

```bash
# Default: fetches 10 posts from aviation247
python get_aviation247_posts.py

# Custom count
python get_aviation247_posts.py --count 5
```

#### Details

- Uses the `apify/facebook-pages-scraper` actor
- Free tier: ~30 runs/month
- Returns structured post data (text, timestamp, URL)
- Runs take 30-90 seconds on Apify's servers

---

### 2. Graph API (If You Manage the Page)

Only works if you (or someone at BRC) are an **admin or editor** of the target
Facebook page. Facebook restricted public page reading after 2018.

#### Setup

1. Go to <https://developers.facebook.com/apps/> and create an app ("Business" type)
2. Add the "Graph API" product
3. In **Graph API Explorer**, select your app, then select the target page
4. Generate a **Page Access Token** (not a User Access Token)
5. Exchange for a long-lived token (~60 days):
   <https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived>
6. Set environment variable:
   ```bash
   export FACEBOOK_ACCESS_TOKEN='your_token_here'
   ```

#### Usage

```bash
python get_aviation247_posts.py --use-graph-api
```

---

### 3. Web Scraping (Last Resort)

Uses a headless browser (Playwright) to load the page directly. **Not recommended**
-- Facebook actively blocks automated browsers and changes their DOM structure.

#### Installation

```bash
pip install playwright
playwright install chromium  # ~300-400MB download
```

#### Usage

```bash
python get_aviation247_posts.py --use-scraper
```

#### Limitations

- Slow (30-60 seconds)
- May be blocked by Facebook at any time
- DOM selectors break when Facebook updates their HTML
- Large browser dependency

---

### Output

All methods save markdown files to `data/scraped/`:

```
data/scraped/facebook_posts_20260222_153042.md
```

Each file contains:
- Post timestamps
- Post content (text)
- Links to original posts

---

### Troubleshooting

**Apify: "actor run failed"**
- Verify your API token is correct
- Check your free tier usage at <https://console.apify.com>

**Graph API: "No posts retrieved"**
- You need a **Page Access Token** for the specific page, not a User token
- Verify at: <https://developers.facebook.com/tools/debug/accesstoken/>
- If you don't manage the page, this method won't work -- use Apify

**Web scraper: no results**
- Facebook has likely changed their HTML structure or blocked the request
- Use Apify instead

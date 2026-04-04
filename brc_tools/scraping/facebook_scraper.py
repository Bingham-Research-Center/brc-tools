"""
Facebook page web scraper using Playwright.

NOT RECOMMENDED - Use Apify (facebook_apify.py) or Graph API instead.

This script uses a headless browser to scrape Facebook pages.
It's slower, less reliable, and may be blocked by Facebook.

Only use this if:
- You cannot get an Apify or Facebook API token
- You need it as a last-resort fallback

Installation:
    pip install playwright
    playwright install chromium

Note: Chromium browser is ~300-400MB

Usage:
    python -m brc_tools.scraping.facebook_scraper --url https://www.facebook.com/aviation247 --count 10

Or with --use-scraper flag in main script:
    python get_aviation247_posts.py --use-scraper
"""

import argparse
import asyncio
from pathlib import Path
from typing import Any, Dict, List

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Error: playwright is not installed. Install with: pip install playwright")
    print("Then run: playwright install chromium")
    raise

from brc_tools.scraping.formatting import format_posts_to_markdown, save_markdown


async def scrape_facebook_posts(page_url: str, num_posts: int = 10) -> List[Dict[str, Any]]:
    """
    Scrape posts from a public Facebook page.

    Args:
        page_url: URL of the Facebook page.
        num_posts: Number of posts to retrieve.

    Returns:
        List of post dicts with keys: index, message, created_time, content, raw_text.
    """
    posts = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()

        try:
            print(f"Loading {page_url}...")
            await page.goto(page_url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)

            # Scroll to load more posts
            print("Scrolling to load posts...")
            for _ in range(5):
                await page.evaluate('window.scrollBy(0, window.innerHeight)')
                await page.wait_for_timeout(2000)

            # Facebook's DOM structure changes frequently
            post_selectors = [
                '[role="article"]',
                'div[data-ad-preview="message"]',
                '.userContentWrapper',
            ]

            post_elements = []
            for selector in post_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    post_elements = elements
                    print(f"Found {len(elements)} elements with selector: {selector}")
                    break

            if not post_elements:
                print("Warning: No post elements found. Facebook may have changed their HTML structure.")
                print("Consider using Apify or the Graph API instead.")
                return []

            for idx, element in enumerate(post_elements[:num_posts]):
                try:
                    text_content = await element.inner_text()

                    # Try to extract timestamp
                    time_elements = await element.query_selector_all(
                        'a[href*="/posts/"], abbr, span[aria-label]'
                    )
                    timestamp = None
                    for time_elem in time_elements:
                        text = await time_elem.inner_text()
                        if any(w in text.lower() for w in ['hour', 'min', 'day', 'week', 'month', 'year', 'yesterday']):
                            timestamp = text
                            break

                    lines = text_content.split('\n')
                    cleaned_lines = [line.strip() for line in lines if line.strip()]

                    post_text = ""
                    for line in cleaned_lines:
                        if len(line) > 50:
                            post_text = line
                            break

                    if not post_text and cleaned_lines:
                        post_text = '\n'.join([l for l in cleaned_lines if len(l) > 20])

                    if post_text:
                        posts.append({
                            'index': idx + 1,
                            'created_time': timestamp,
                            'message': post_text,
                            'content': post_text,
                            'raw_text': text_content,
                        })

                except Exception as e:
                    print(f"Error extracting post {idx + 1}: {e}")
                    continue

        except PlaywrightTimeout:
            print("Error: Page load timeout. Facebook may be blocking automated access.")
        except Exception as e:
            print(f"Error during scraping: {e}")
        finally:
            await browser.close()

    return posts


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Scrape recent posts from a public Facebook page'
    )
    parser.add_argument(
        '--url',
        default='https://www.facebook.com/aviation247',
        help='Facebook page URL (default: aviation247)',
    )
    parser.add_argument(
        '--count', type=int, default=10,
        help='Number of posts to retrieve (default: 10)',
    )
    parser.add_argument(
        '--output', type=Path,
        help='Output directory (default: data/scraped/)',
    )

    args = parser.parse_args()

    print(f"Scraping {args.count} posts from {args.url}")
    print("Note: This may take 30-60 seconds...")

    posts = await scrape_facebook_posts(args.url, args.count)

    if not posts:
        print("\nNo posts found. Consider using Apify or Graph API instead.")
        return

    print(f"\nSuccessfully scraped {len(posts)} posts!")

    page_name = args.url.split('/')[-1]
    markdown = format_posts_to_markdown(posts, page_name, args.url)
    output_path = save_markdown(markdown, args.output)

    print(f"\nMarkdown saved to: {output_path}")
    print("\nPreview:")
    print("=" * 60)
    print(markdown[:500] + "..." if len(markdown) > 500 else markdown)


if __name__ == '__main__':
    asyncio.run(main())

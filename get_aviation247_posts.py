#!/usr/bin/env python3
"""
Quick-start script for fetching Facebook posts from aviation247.

Default method: Apify (works without managing the Facebook page).
Alternatives:
    --use-graph-api   Facebook Graph API (requires page admin access token)
    --use-scraper     Playwright headless browser (fragile, last resort)

For setup instructions, see brc_tools/scraping/README.md.
"""

import argparse
import os
import sys
from pathlib import Path

from brc_tools.scraping.formatting import format_posts_to_markdown, save_markdown


def main():
    parser = argparse.ArgumentParser(
        description='Fetch Facebook posts from aviation247',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='See brc_tools/scraping/README.md for setup instructions.',
    )
    parser.add_argument(
        '--page-id',
        default='aviation247',
        help='Facebook page ID or username (default: aviation247)',
    )
    parser.add_argument(
        '--count',
        type=int,
        default=10,
        help='Number of posts to retrieve (default: 10)',
    )
    parser.add_argument(
        '--use-graph-api',
        action='store_true',
        help='Use Facebook Graph API (requires FACEBOOK_ACCESS_TOKEN)',
    )
    parser.add_argument(
        '--use-scraper',
        action='store_true',
        help='Use Playwright web scraping (slow, fragile, last resort)',
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output directory (default: data/scraped/)',
    )

    args = parser.parse_args()
    page_url = f'https://www.facebook.com/{args.page_id}'

    # --- Playwright scraper path ---
    if args.use_scraper:
        print("Web scraping mode requested...")
        try:
            from brc_tools.scraping.facebook_scraper import scrape_facebook_posts
            import asyncio

            print(f"Scraping {args.count} posts from {page_url}...")
            print("Note: This may take 30-60 seconds and may be blocked by Facebook.")

            posts = asyncio.run(scrape_facebook_posts(page_url, args.count))

            if posts:
                print(f"Successfully scraped {len(posts)} posts!")
                markdown = format_posts_to_markdown(posts, args.page_id, page_url)
                output_path = save_markdown(markdown, args.output)
                print(f"Saved to: {output_path}")
            else:
                print("Web scraping failed. Facebook may be blocking access.")
                print("\nRecommendation: Use Apify instead (remove --use-scraper flag).")

        except ImportError:
            print("Error: Playwright not installed.")
            print("\nTo use web scraping, install:")
            print("  pip install playwright")
            print("  playwright install chromium")
            print("\nOr use Apify instead (remove --use-scraper flag).")
            sys.exit(1)

        return

    # --- Graph API path ---
    if args.use_graph_api:
        from brc_tools.scraping.facebook_graph_api import get_page_posts

        access_token = os.getenv('FACEBOOK_ACCESS_TOKEN')

        if not access_token:
            print("Error: No Facebook access token found.")
            print("\n" + "=" * 70)
            print("FACEBOOK ACCESS TOKEN REQUIRED")
            print("=" * 70)
            print("\nThis method requires a Page Access Token for the target page.")
            print("You must be an admin/editor of the Facebook page.\n")
            print("Setup:")
            print("  1. Visit https://developers.facebook.com/apps/")
            print("  2. Create an app -> Add 'Graph API' product")
            print("  3. Graph API Explorer -> select your page -> Generate Page Access Token")
            print("  4. export FACEBOOK_ACCESS_TOKEN='your_token_here'")
            print("\nIf you don't manage the page, use Apify instead (remove --use-graph-api flag).")
            print("=" * 70)
            sys.exit(1)

        print(f"Using Facebook Graph API to fetch {args.count} posts from {args.page_id}...")
        posts = get_page_posts(args.page_id, access_token, args.count)

        if not posts:
            print("Graph API failed. Check your token and page ID.")
            print("\nTroubleshooting:")
            print("  - Verify token: https://developers.facebook.com/tools/debug/accesstoken/")
            print("  - Ensure you have a Page Access Token (not a User token)")
            print("  - The page must be one you manage")
            sys.exit(1)

        print(f"Successfully fetched {len(posts)} posts!")
        markdown = format_posts_to_markdown(posts, args.page_id, page_url)
        output_path = save_markdown(markdown, args.output)
        print(f"Saved to: {output_path}")
        _print_preview(markdown)
        return

    # --- Default: Apify path ---
    api_token = os.getenv('APIFY_API_TOKEN')

    if not api_token:
        print("Error: No Apify API token found.")
        print("\n" + "=" * 70)
        print("APIFY API TOKEN REQUIRED")
        print("=" * 70)
        print("\nSetup (free, ~2 minutes):")
        print("  1. Sign up at https://apify.com (no credit card needed)")
        print("  2. Go to Settings -> Integrations -> copy your API token")
        print("  3. export APIFY_API_TOKEN='your_token_here'")
        print("\nFree tier allows ~30 runs/month, enough for occasional use.")
        print("\nAlternative methods:")
        print("  --use-graph-api   (if you manage the Facebook page)")
        print("  --use-scraper     (Playwright, slow and unreliable)")
        print("=" * 70)
        sys.exit(1)

    from brc_tools.scraping.facebook_apify import get_page_posts as apify_get_posts

    print(f"Using Apify to fetch {args.count} posts from {args.page_id}...")
    posts = apify_get_posts(page_url, api_token, args.count)

    if not posts:
        print("Apify returned no posts. Check your API token and try again.")
        sys.exit(1)

    print(f"Successfully fetched {len(posts)} posts!")
    markdown = format_posts_to_markdown(posts, args.page_id, page_url)
    output_path = save_markdown(markdown, args.output)
    print(f"Saved to: {output_path}")
    _print_preview(markdown)


def _print_preview(markdown: str):
    print("\nPreview:")
    print("=" * 60)
    print(markdown[:500] + "..." if len(markdown) > 500 else markdown)


if __name__ == '__main__':
    main()

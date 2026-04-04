"""
Facebook page post fetcher using the Apify platform.

This is the recommended method when you do not manage the target Facebook page.
Apify's Facebook Pages Scraper handles authentication and anti-bot measures.

Requirements:
    pip install apify-client
    export APIFY_API_TOKEN='your_token_here'

Free tier: ~30 actor runs / month (no credit card required).
Sign up at https://apify.com
"""

import os
from typing import Any, Dict, List


def get_page_posts(
    page_url: str,
    api_token: str,
    num_posts: int = 10,
) -> List[Dict[str, Any]]:
    """
    Fetch recent posts from a public Facebook page via Apify.

    Uses the ``apify/facebook-pages-scraper`` actor.

    Args:
        page_url: Full URL of the Facebook page
                  (e.g. ``https://www.facebook.com/aviation247``).
        api_token: Apify API token.
        num_posts: Maximum number of posts to return.

    Returns:
        List of post dicts with keys: message, created_time, permalink_url, index.
        Returns an empty list on failure.
    """
    try:
        from apify_client import ApifyClient
    except ImportError:
        print("Error: apify-client is not installed.")
        print("Install with:  pip install apify-client")
        return []

    client = ApifyClient(api_token)

    run_input = {
        "startUrls": [{"url": page_url}],
        "resultsLimit": num_posts,
    }

    try:
        print(f"Starting Apify actor for {page_url} ...")
        run = client.actor("apify/facebook-pages-scraper").call(run_input=run_input)
    except Exception as e:
        print(f"Apify actor run failed: {e}")
        return []

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        print("Error: Apify run did not return a dataset ID.")
        return []

    items = list(client.dataset(dataset_id).iterate_items())

    posts: List[Dict[str, Any]] = []
    for idx, item in enumerate(items[:num_posts], 1):
        posts.append({
            "index": idx,
            "message": item.get("text") or item.get("message") or "",
            "created_time": item.get("time") or item.get("timestamp") or None,
            "permalink_url": item.get("url") or item.get("postUrl") or "",
        })

    return posts


def main():
    """CLI entry point for standalone testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch Facebook page posts via Apify"
    )
    parser.add_argument(
        "--url",
        default="https://www.facebook.com/aviation247",
        help="Facebook page URL (default: aviation247)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of posts to retrieve (default: 10)",
    )
    args = parser.parse_args()

    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        print("Error: APIFY_API_TOKEN environment variable not set.")
        print("\nSetup:")
        print("  1. Sign up at https://apify.com (free)")
        print("  2. Copy your API token from Settings -> Integrations")
        print("  3. export APIFY_API_TOKEN='your_token'")
        return

    posts = get_page_posts(args.url, api_token, args.count)

    if not posts:
        print("No posts retrieved.")
        return

    print(f"Fetched {len(posts)} posts:\n")
    for p in posts:
        print(f"--- Post {p['index']} ({p['created_time'] or 'unknown date'}) ---")
        print(p["message"][:200] or "[no text]")
        print()


if __name__ == "__main__":
    main()

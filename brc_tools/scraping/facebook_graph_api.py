"""
Facebook Graph API client for fetching page posts.

Requires a Page Access Token for the target page (you must be an admin/editor).
Set via FACEBOOK_ACCESS_TOKEN env var.

For setup instructions, see README.md in this directory.
"""

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

import requests

from brc_tools.scraping.formatting import format_posts_to_markdown, save_markdown


def get_page_posts(page_id: str, access_token: str, num_posts: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch posts from a Facebook page using Graph API.

    Args:
        page_id: Facebook page ID or username.
        access_token: Facebook Page Access Token.
        num_posts: Number of posts to retrieve.

    Returns:
        List of post dicts with keys: id, message, created_time, permalink_url, full_picture.
    """
    url = f'https://graph.facebook.com/v21.0/{page_id}/posts'
    params = {
        'access_token': access_token,
        'fields': 'id,message,created_time,permalink_url,full_picture',
        'limit': num_posts,
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if 'error' in data:
            print(f"API Error: {data['error']['message']}")
            return []

        return data.get('data', [])

    except requests.RequestException as e:
        print(f"Request error: {e}")
        return []


def main():
    """CLI entry point for standalone use."""
    parser = argparse.ArgumentParser(
        description='Fetch Facebook posts using Graph API (requires Page Access Token)'
    )
    parser.add_argument(
        '--page-id', default='aviation247',
        help='Facebook page ID or username (default: aviation247)',
    )
    parser.add_argument(
        '--count', type=int, default=10,
        help='Number of posts to retrieve (default: 10)',
    )
    parser.add_argument(
        '--output', type=Path,
        help='Output directory (default: data/scraped/)',
    )
    parser.add_argument(
        '--token',
        help='Facebook access token (or set FACEBOOK_ACCESS_TOKEN env var)',
    )

    args = parser.parse_args()

    access_token = args.token or os.getenv('FACEBOOK_ACCESS_TOKEN')
    if not access_token:
        print("Error: No access token provided!")
        print("\nOptions:")
        print("1. Set env var: export FACEBOOK_ACCESS_TOKEN=your_token")
        print("2. Pass via CLI: --token your_token")
        return

    print(f"Fetching {args.count} posts from {args.page_id}...")

    posts = get_page_posts(args.page_id, access_token, args.count)
    if not posts:
        print("No posts retrieved. Check your access token and page ID.")
        return

    print(f"Successfully fetched {len(posts)} posts!")

    page_url = f"https://www.facebook.com/{args.page_id}"
    markdown = format_posts_to_markdown(posts, args.page_id, page_url)
    output_path = save_markdown(markdown, args.output)

    print(f"\nMarkdown saved to: {output_path}")
    print("\nPreview:")
    print("=" * 60)
    print(markdown[:500] + "..." if len(markdown) > 500 else markdown)


if __name__ == '__main__':
    main()

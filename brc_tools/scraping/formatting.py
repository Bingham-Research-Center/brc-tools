"""
Shared formatting and output utilities for scraped social media posts.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def format_posts_to_markdown(posts: List[Dict[str, Any]], page_name: str, page_url: str) -> str:
    """
    Format posts into a Markdown document.

    Args:
        posts: List of post dicts. Each must have 'message' (str) and
               'created_time' (ISO-8601 str or None). May also have
               'permalink_url' and 'index'.
        page_name: Display name for the page header.
        page_url: Full URL to the page.

    Returns:
        Markdown-formatted string.
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    md_lines = [
        f"# Facebook Posts - {page_name}",
        "",
        f"**Source:** [{page_url}]({page_url})",
        f"**Retrieved:** {timestamp}",
        f"**Posts:** {len(posts)}",
        "",
        "---",
        "",
    ]

    for idx, post in enumerate(posts, 1):
        created_time = post.get('created_time') or 'Unknown'
        if created_time != 'Unknown':
            try:
                dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                created_time = dt.strftime('%Y-%m-%d %H:%M UTC')
            except ValueError:
                pass  # keep raw string

        message = post.get('message') or post.get('content') or '[No text content]'
        permalink = post.get('permalink_url', '')

        md_lines.extend([
            f"## Post {post.get('index', idx)}",
            "",
            f"**Posted:** {created_time}",
        ])
        if permalink:
            md_lines.append(f"**Link:** [{permalink}]({permalink})")
        md_lines.extend([
            "",
            message,
            "",
            "---",
            "",
        ])

    return '\n'.join(md_lines)


def save_markdown(content: str, output_dir: Path = None) -> Path:
    """
    Save markdown content to a timestamped file.

    Args:
        content: Markdown string.
        output_dir: Target directory. Defaults to ``data/scraped/`` relative
                    to the project root.

    Returns:
        Path to the saved file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / 'data' / 'scraped'

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    filepath = output_dir / f"facebook_posts_{timestamp}.md"

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return filepath

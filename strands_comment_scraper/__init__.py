"""Strands Agents tools for Reddit and Hacker News threads exported with Comment Scraper."""

from importlib import metadata

from strands_comment_scraper.tools import (
    comment_export_stats,
    filter_comments,
    get_comment,
    read_comment_export,
)

try:
    __version__ = metadata.version(__package__ or __name__)
except metadata.PackageNotFoundError:
    # Running from a source checkout that was never installed.
    __version__ = ""

__all__ = [
    "comment_export_stats",
    "filter_comments",
    "get_comment",
    "read_comment_export",
    "__version__",
]

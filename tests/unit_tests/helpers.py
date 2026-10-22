"""Builds small exports for tests, in the shape the extension writes."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent.parent / "fixtures"

ENVELOPE = {
    "schema_version": 1,
    "exported_at": "2026-10-10T12:00:00.000Z",
    "generator": "Comment Scraper",
}
META = {
    "source": "reddit",
    "thread_id": "t1",
    "thread_title": "Thread t1",
    "permalink": "https://www.reddit.com/r/test/comments/t1/",
    "fetch_path": "json",
    "task_state": "all_known_fetched",
    "stop_reason": None,
    "fetched": 1,
    "known_unfetched_at_least": 0,
    "reported_by_source": 1,
    "fetched_at": "2026-10-10T12:00:00.000Z",
}


def record(
    comment_id: str | None, parent_id: str | None, body: str = "text", **extra: Any
) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "source": "reddit",
        "record_type": "post" if comment_id is None else "comment",
        "thread_id": "t1",
        "thread_title": "Thread t1",
        "subreddit": "test",
        "comment_id": comment_id,
        "parent_id": parent_id,
        "depth": None if comment_id is None else 0,
        "score": 1,
        "score_hidden": False,
        "created_utc": "2026-10-09T12:00:00.000Z",
        "edited_utc": None,
        "is_op": False,
        "body": body,
        "permalink": f"https://www.reddit.com/r/test/comments/t1/_/{comment_id}/",
        "comment_state": "normal",
    }
    base.update(extra)
    return base


def write_export(tmp_path: Path, *threads: Any, name: str = "export.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({**ENVELOPE, "threads": list(threads)}))
    return path

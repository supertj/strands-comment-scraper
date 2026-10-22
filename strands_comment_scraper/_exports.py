"""Reads Comment Scraper JSON exports from disk and checks them.

Comment Scraper is a browser extension that exports Reddit and Hacker News threads. It writes
two JSON formats, "JSON, one row per comment" and "JSON, replies nested"; both hold one or more
threads, each with a meta block and the thread's records. This module turns either format into
the same thing: the records in tree order (the post, then the comments depth first), which is
the order the extension numbers comments in.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

GENERATOR = "Comment Scraper"

# Large enough for a 10,000-comment thread. The path comes from the model, so this stops a
# wrong guess (a video, a disk image) from being read into memory.
MAX_FILE_BYTES = 200 * 1024 * 1024


def _is_text(value: object) -> bool:
    return isinstance(value, str)


def _is_text_or_none(value: object) -> bool:
    return value is None or isinstance(value, str)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_int_or_none(value: object) -> bool:
    return value is None or _is_int(value)


def _is_number_or_none(value: object) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


# Every field the tools read. A file can carry the generator marker and still be cut off or
# edited by hand; saying so beats showing the model half a thread.
_META_CHECKS: dict[str, Callable[[object], bool]] = {
    "source": lambda value: value in ("reddit", "hn"),
    "thread_id": _is_text,
    "thread_title": _is_text,
    "permalink": _is_text,
    "fetch_path": lambda value: value in ("json", "dom", "api"),
    "task_state": lambda value: value in ("all_known_fetched", "partial", "limit_reached"),
    "stop_reason": _is_text_or_none,
    "fetched": _is_int,
    "known_unfetched_at_least": _is_int,
    "reported_by_source": _is_int_or_none,
    "fetched_at": _is_text,
}

_RECORD_CHECKS: dict[str, Callable[[object], bool]] = {
    "record_type": lambda value: value in ("post", "comment"),
    "comment_id": _is_text_or_none,
    "parent_id": _is_text_or_none,
    "depth": _is_int_or_none,
    "score": _is_number_or_none,
    "score_hidden": lambda value: isinstance(value, bool),
    "created_utc": _is_text,
    "edited_utc": _is_text_or_none,
    "is_op": lambda value: isinstance(value, bool),
    "body": _is_text,
    "permalink": _is_text,
    # An unknown state would otherwise be shown as if the comment were deleted.
    "comment_state": lambda value: value in ("normal", "deleted", "removed"),
    "subreddit": _is_text_or_none,
}


@dataclass(frozen=True)
class Thread:
    """One exported thread, with its records in tree order."""

    meta: dict[str, Any]
    records: list[dict[str, Any]]
    # comment_id -> N in [cN]: comments in tree order, counted from 1, deleted ones included,
    # the same numbering as the extension's Markdown export.
    numbers: dict[str, int]

    @property
    def id(self) -> str:
        return f"{self.meta['source']}:{self.meta['thread_id']}"

    @property
    def post(self) -> dict[str, Any]:
        return next(record for record in self.records if record["record_type"] == "post")

    @property
    def comments(self) -> list[dict[str, Any]]:
        return [record for record in self.records if record["record_type"] == "comment"]


def _missing_field(value: object, checks: dict[str, Callable[[object], bool]]) -> str | None:
    """The first field that is absent or has the wrong type, or None when all pass."""
    if not isinstance(value, dict):
        return "not an object"
    for name, check in checks.items():
        if name not in value or not check(value[name]):
            return name
    return None


def _reject_constant(name: str) -> float:
    # The extension writes JSON with JSON.stringify, which never emits NaN or Infinity.
    raise ValueError(f"not valid JSON: {name}")


def _flatten_nested(post: object, comments: object) -> list[object] | None:
    """Walks a nested export back into tree order: the post, then the comments depth first.

    A loop rather than recursion, because a long "continue this thread" chain can be
    thousands of replies deep. Returns None if a replies list is missing or not a list.
    """
    if not isinstance(comments, list):
        return None
    records: list[object] = [post]
    finished = object()
    stack = [iter(comments)]
    while stack:
        node = next(stack[-1], finished)
        if node is finished:
            stack.pop()
            continue
        if not isinstance(node, dict) or not isinstance(node.get("replies"), list):
            return None
        records.append({key: value for key, value in node.items() if key != "replies"})
        stack.append(iter(node["replies"]))
    return records


class _DamagedThread(ValueError):
    pass


def _thread(entry: object) -> Thread:
    """One entry of an export's "threads" list, checked."""
    if not isinstance(entry, dict):
        raise _DamagedThread("not an object")
    problem = _missing_field(entry.get("meta"), _META_CHECKS)
    if problem:
        raise _DamagedThread(f"meta field {problem}")
    if isinstance(entry.get("records"), list):
        records = entry["records"]
    elif "post" in entry:
        records = _flatten_nested(entry["post"], entry.get("comments"))
        if records is None:
            raise _DamagedThread("a replies list is missing")
    else:
        raise _DamagedThread("no records")

    numbers: dict[str, int] = {}
    posts = 0
    for record in records:
        problem = _missing_field(record, _RECORD_CHECKS)
        if problem:
            raise _DamagedThread(f"record field {problem}")
        if record["record_type"] == "post":
            posts += 1
            continue
        # [cN] numbers are keyed by comment id, so an empty or repeated id would give two
        # comments one number and a citation would point at the wrong one.
        comment_id = record["comment_id"]
        if not comment_id or comment_id in numbers:
            raise _DamagedThread(f"empty or repeated comment id {comment_id!r}")
        numbers[comment_id] = len(numbers) + 1
    if posts != 1:
        raise _DamagedThread(f"{posts} post records")
    return Thread(
        meta=entry["meta"], records=cast("list[dict[str, Any]]", records), numbers=numbers
    )


def read_export(path: str | os.PathLike[str]) -> list[Thread]:
    """The threads in one export file. Raises ValueError with a message meant for the model."""
    file = Path(path).expanduser()
    not_an_export = (
        f"{file} is not a Comment Scraper JSON export. Export the thread as "
        '"JSON, one row per comment" or "JSON, replies nested"; '
        "CSV and Markdown exports can't be read."
    )
    try:
        if file.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(not_an_export)
        # utf-8-sig: a byte order mark, which some editors add on save, is skipped.
        text = file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(not_an_export) from None
    except OSError as error:
        raise ValueError(f"Can't read {file}: {error.strerror or error}.") from None

    try:
        parsed = json.loads(text, parse_constant=_reject_constant)
    except RecursionError:
        raise ValueError(
            f"{file}: the replies are nested too deeply for Python's JSON parser. "
            'Export the thread as "JSON, one row per comment" instead.'
        ) from None
    except ValueError:
        raise ValueError(not_an_export) from None
    if (
        not isinstance(parsed, dict)
        or parsed.get("generator") != GENERATOR
        or not isinstance(parsed.get("threads"), list)
    ):
        raise ValueError(not_an_export)
    if not parsed["threads"]:
        raise ValueError(f"{file} is a Comment Scraper export with no threads in it.")

    threads = []
    for index, entry in enumerate(parsed["threads"], start=1):
        try:
            threads.append(_thread(entry))
        except _DamagedThread as error:
            raise ValueError(f"{file}: thread {index} is damaged ({error}).") from None
    return threads

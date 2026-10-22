"""Optional check against real exports, which aren't committed because they hold other
people's comments. Put JSON exports in a folder and run:

    CS_REAL_EXPORTS_DIR=/path/to/exports uv run pytest tests/unit_tests/test_real_exports.py

Every thread is read page by page to the end. If a thread was also exported as Markdown and
the .md file sits next to the .json with the same name (the extension names both after the
thread title), every comment line in the Markdown file must appear in what the tools return.
The Markdown export can leave out short comments, so the check runs one way only.
"""

import os
import re
from pathlib import Path

import pytest

from strands_comment_scraper import comment_export_stats, read_comment_export
from strands_comment_scraper._exports import read_export

FOLDER = os.environ.get("CS_REAL_EXPORTS_DIR")
pytestmark = pytest.mark.skipif(
    not FOLDER, reason="set CS_REAL_EXPORTS_DIR to a folder of real exports"
)
COMMENT_LINE = re.compile(r"^\[c(\d+)\].*\)$", re.MULTILINE)
NEXT_OFFSET = re.compile(r"again with offset=(\d+) for more\.$")


def real_files() -> list[Path]:
    return sorted(Path(FOLDER).glob("*.json")) if FOLDER else []


@pytest.mark.parametrize("path", real_files(), ids=lambda path: path.name)
def test_real_export(path: Path) -> None:
    threads = read_export(path)
    assert comment_export_stats(str(path))
    for thread in threads:
        pages = []
        offset = 0
        while True:
            page = read_comment_export(str(path), thread=thread.id, offset=offset)
            pages.append(page)
            more = NEXT_OFFSET.search(page)
            if not more:
                break
            offset = int(more.group(1))
        numbers = [int(number) for page in pages for number in COMMENT_LINE.findall(page)]
        assert numbers == list(range(1, len(thread.comments) + 1))

        markdown = path.with_suffix(".md")
        if markdown.exists() and len(threads) == 1:
            ours = {line for page in pages for line in page.splitlines()}
            theirs = COMMENT_LINE.finditer(markdown.read_text(encoding="utf-8"))
            missing = [match.group(0) for match in theirs if match.group(0) not in ours]
            assert not missing

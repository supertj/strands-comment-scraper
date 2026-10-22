import json
from pathlib import Path
from typing import Any

import pytest

from strands_comment_scraper import _exports
from strands_comment_scraper._exports import read_export
from tests.unit_tests.helpers import ENVELOPE, FIXTURES, META, record, write_export


def test_flat_and_nested_exports_give_the_same_threads() -> None:
    flat = read_export(FIXTURES / "which-crm.json")
    nested = read_export(FIXTURES / "which-crm-nested.json")
    assert flat == nested
    thread = flat[0]
    assert thread.id == "reddit:crm1"
    assert thread.post["record_type"] == "post"
    assert [record["comment_id"] for record in thread.comments] == [
        "a1",
        "a2",
        "a3",
        "a8",
        "a4",
        "a5",
        "a6",
        "a7",
    ]


def test_numbers_match_the_extensions_markdown_export() -> None:
    golden = json.loads((FIXTURES / "markdown-lines.json").read_text())
    for name, threads in golden.items():
        loaded = read_export(FIXTURES / name)
        assert [thread.meta["thread_id"] for thread in loaded] == [
            thread["thread_id"] for thread in threads
        ]
        for thread, expected in zip(loaded, threads):
            assert thread.numbers == {
                comment["comment_id"]: comment["number"] for comment in expected["comments"]
            }


def test_home_directory_and_byte_order_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "bom.json"
    path.write_text(
        "﻿" + json.dumps({**ENVELOPE, "threads": [{"meta": META, "records": [record(None, None)]}]}),
        encoding="utf-8",
    )
    assert len(read_export("~/bom.json")) == 1


@pytest.mark.parametrize(
    "content",
    [
        '{"name": "not-an-export"}',
        '{"schema_version": 1, "generator": "Comment Scraper", "threads": [',
        "comment_id,body\n1,hello\n",
        '{"schema_version": 1, "generator": "Comment Scraper", "threads": {}}',
        '{"schema_version": 1, "generator": "Comment Scraper", "threads": [], "x": NaN}',
    ],
)
def test_files_that_are_not_exports_are_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "file.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="is not a Comment Scraper JSON export"):
        read_export(path)


def test_binary_and_oversized_files_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "photo.json"
    binary.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    with pytest.raises(ValueError, match="is not a Comment Scraper JSON export"):
        read_export(binary)

    path = write_export(tmp_path, {"meta": META, "records": [record(None, None)]})
    monkeypatch.setattr(_exports, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="is not a Comment Scraper JSON export"):
        read_export(path)


def test_missing_files_and_folders_say_what_went_wrong(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Can't read .*missing.json: No such file"):
        read_export(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="Can't read"):
        read_export(tmp_path)


def test_export_with_no_threads_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no threads in it"):
        read_export(write_export(tmp_path))


@pytest.mark.parametrize(
    ("thread", "reason"),
    [
        (7, "not an object"),
        (
            {"meta": {**META, "source": "twitter"}, "records": [record(None, None)]},
            "meta field source",
        ),
        (
            {"meta": {**META, "task_state": "done"}, "records": [record(None, None)]},
            "meta field task_state",
        ),
        (
            {"meta": {**META, "fetched": "1"}, "records": [record(None, None)]},
            "meta field fetched",
        ),
        ({"meta": META}, "no records"),
        (
            {"meta": META, "records": [record(None, None), {"record_type": "comment"}]},
            "record field comment_id",
        ),
        (
            {"meta": META, "records": [record(None, None), record("c1", "t1", score="12")]},
            "record field score",
        ),
        (
            {
                "meta": META,
                "records": [record(None, None), record("c1", "t1", comment_state="normla")],
            },
            "record field comment_state",
        ),
        ({"meta": META, "records": [record("c1", "t1")]}, "0 post records"),
        (
            {"meta": META, "records": [record(None, None), record("a", "t1"), record("a", "t1")]},
            "repeated comment id 'a'",
        ),
        (
            {"meta": META, "records": [record(None, None), record("", "t1")]},
            "empty or repeated comment id ''",
        ),
        (
            {
                "meta": META,
                "post": record(None, None),
                "comments": [{**record("c1", "t1"), "replies": None}],
            },
            "replies list is missing",
        ),
        (
            {
                "meta": META,
                "post": record(None, None),
                "comments": [{**record("c1", "t1"), "replies": [None]}],
            },
            "replies list is missing",
        ),
    ],
)
def test_damaged_threads_are_refused_with_the_file_and_reason(
    tmp_path: Path, thread: Any, reason: str
) -> None:
    path = write_export(tmp_path, {"meta": META, "records": [record(None, None)]}, thread)
    with pytest.raises(ValueError, match="thread 2 is damaged") as error:
        read_export(path)
    assert reason in str(error.value)
    assert str(path) in str(error.value)


def nested_chain(depth: int) -> str:
    """A nested export whose replies form one chain. Built as text because json.dumps
    recurses too."""
    opening = "".join(
        json.dumps(record(f"c{index}", f"c{index - 1}" if index else "t1"))[:-1] + ', "replies": ['
        for index in range(depth)
    )
    thread = (
        '{"meta": '
        + json.dumps(META)
        + ', "post": '
        + json.dumps(record(None, None))
        + ', "comments": ['
        + opening
        + "]}" * depth
        + "]}"
    )
    return json.dumps(ENVELOPE)[:-1] + ', "threads": [' + thread + "]}"


def test_deeply_nested_exports_load_or_point_to_the_flat_format(tmp_path: Path) -> None:
    shallow = tmp_path / "shallow.json"
    shallow.write_text(nested_chain(300))
    assert len(read_export(shallow)[0].comments) == 300

    # How deep Python's JSON parser can go depends on the Python version and the stack size,
    # so a very deep file either loads in full or fails with a message that says what to do.
    deep = tmp_path / "deep.json"
    deep.write_text(nested_chain(20_000))
    try:
        threads = read_export(deep)
    except ValueError as error:
        assert "one row per comment" in str(error)
    else:
        assert len(threads[0].comments) == 20_000


def test_parser_recursion_limit_is_reported_with_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def too_deep(*args: Any, **kwargs: Any) -> Any:
        raise RecursionError

    monkeypatch.setattr("strands_comment_scraper._exports.json.loads", too_deep)
    path = write_export(tmp_path, {"meta": META, "records": [record(None, None)]})
    with pytest.raises(ValueError, match="one row per comment"):
        read_export(path)

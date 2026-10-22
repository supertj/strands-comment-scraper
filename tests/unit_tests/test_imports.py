from strands_comment_scraper import __all__

EXPECTED_ALL = [
    "comment_export_stats",
    "filter_comments",
    "get_comment",
    "read_comment_export",
    "__version__",
]


def test_all_imports() -> None:
    assert sorted(EXPECTED_ALL) == sorted(__all__)

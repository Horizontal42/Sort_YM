import pytest

from sort_ym import language


@pytest.mark.parametrize(
    "text_language,expected",
    [
        ("ru", "RU"),
        ("RU", "RU"),
        ("en", "INT"),
        ("de", "INT"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_api_language(text_language, expected):
    assert language.normalize_api_language(text_language) == expected


@pytest.mark.parametrize(
    "genre_raw,expected",
    [
        ("rusrap", "RU"),
        ("shanson", "RU"),
        ("rock", None),
        (None, None),
    ],
)
def test_genre_hint(genre_raw, expected):
    assert language.genre_hint(genre_raw) == expected


@pytest.mark.parametrize(
    "title,artists,expected",
    [
        ("Кино не для всех", ["Земфира"], "RU"),
        ("Bohemian Rhapsody", ["Queen"], "INT"),
        ("AB", ["АБ"], None),  # ровно поровну — не решаем
        ("123", [], None),
        ("", [], None),
    ],
)
def test_alphabet_heuristic(title, artists, expected):
    assert language.alphabet_heuristic(title, artists) == expected


def test_detect_language_prefers_api_over_everything():
    result = language.detect_language(
        title="Bohemian Rhapsody",
        artists=["Queen"],
        genre_raw="rusrap",
        api_language="ru",
    )
    assert result == "RU"


def test_detect_language_falls_back_to_genre_hint():
    result = language.detect_language(
        title="???",
        artists=[],
        genre_raw="shanson",
        api_language=None,
    )
    assert result == "RU"


def test_detect_language_falls_back_to_alphabet():
    result = language.detect_language(
        title="Отпусти меня",
        artists=["ДДТ"],
        genre_raw="rock",
        api_language=None,
    )
    assert result == "RU"


def test_detect_language_unknown_when_nothing_matches():
    result = language.detect_language(
        title="123",
        artists=[],
        genre_raw=None,
        api_language=None,
    )
    assert result == "UNKNOWN"

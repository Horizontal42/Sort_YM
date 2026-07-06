import pytest

from sort_ym import genres


@pytest.fixture
def catalog():
    return {
        "rock": {"title": "Рок", "root_id": "rock"},
        "rusrock": {"title": "Русский рок", "root_id": "rock"},
        "postrock": {"title": "Пост-рок", "root_id": "postrock"},
        "rap": {"title": "Рэп", "root_id": "rap"},
        "trap": {"title": "Трэп", "root_id": "rap"},
    }


@pytest.mark.parametrize(
    "genre_raw,expected",
    [
        ("rock", "rock"),
        ("rusrock", "rock"),
        ("postrock", "indie-alt"),
        ("rap", "rap"),
        ("trap", "rap"),
        (None, "other"),
        ("", "other"),
        ("totally-unknown-slug", "other"),
    ],
)
def test_bucket_for(catalog, genre_raw, expected):
    assert genres.bucket_for(genre_raw, catalog) == expected


def test_flatten_catalog_walks_sub_genres():
    class FakeGenre:
        def __init__(self, id_, title, sub_genres=None):
            self.id = id_
            self.title = title
            self.sub_genres = sub_genres or []

    root = FakeGenre("rock", "Рок", [FakeGenre("rusrock", "Русский рок")])

    flat = genres.flatten_catalog([root])

    assert flat["rock"] == {"title": "Рок", "root_id": "rock"}
    assert flat["rusrock"] == {"title": "Русский рок", "root_id": "rock"}

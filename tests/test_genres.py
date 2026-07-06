import pytest

from sort_ym import genres


@pytest.fixture
def catalog():
    # Форма реального дерева client.genres(): "rock"/"rusrock" - подгенры, реальный
    # корень называется "allrock", а не "rock" (проверено на живом каталоге).
    return {
        "allrock": {"title": "Рок", "root_id": "allrock"},
        "rock": {"title": "Иностранный рок", "root_id": "allrock"},
        "rusrock": {"title": "Русский рок", "root_id": "allrock"},
        "alternative": {"title": "Альтернатива", "root_id": "alternative"},
        "rap": {"title": "Рэп и хип-хоп", "root_id": "rap"},
        "trap": {"title": "Трэп", "root_id": "rap"},
    }


@pytest.mark.parametrize(
    "genre_raw,expected",
    [
        ("allrock", "rock"),
        ("rock", "rock"),
        ("rusrock", "rock"),
        ("alternative", "indie-alt"),
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

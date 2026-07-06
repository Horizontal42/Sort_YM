import pytest

from sort_ym import genres


@pytest.fixture
def catalog():
    # Форма реального дерева client.genres(): "rock"/"rusrock"/"hardrock"/"dnb" - подгенры,
    # "allrock"/"alternative"/"indie"/"punk"/"rap"/"metal" - настоящие корни (root_id == сам слаг).
    # Проверено на живом каталоге (cache/genre_catalog.json).
    return {
        "allrock": {"title": "Рок", "root_id": "allrock"},
        "rock": {"title": "Иностранный рок", "root_id": "allrock"},
        "rusrock": {"title": "Русский рок", "root_id": "allrock"},
        "hardrock": {"title": "Хард-рок", "root_id": "allrock"},
        "alternative": {"title": "Альтернатива", "root_id": "alternative"},
        "indie": {"title": "Инди", "root_id": "indie"},
        "punk": {"title": "Панк", "root_id": "punk"},
        "metal": {"title": "Метал", "root_id": "metal"},
        "numetal": {"title": "Ню-метал", "root_id": "metal"},
        "rap": {"title": "Рэп и хип-хоп", "root_id": "rap"},
        "trap": {"title": "Трэп", "root_id": "rap"},
        "electronics": {"title": "Электроника", "root_id": "electronics"},
        "dnb": {"title": "Драм-н-бейс", "root_id": "electronics"},
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


@pytest.mark.parametrize(
    "fines,expected",
    [
        ([], None),
        (["indie"], "indie"),
        (["indie", "metal", "indie"], "indie"),
        (["indie", "metal"], "indie"),  # равенство частот -> первый по порядку
    ],
)
def test_dominant(fines, expected):
    assert genres.dominant(fines) == expected


@pytest.mark.parametrize(
    "genre_raw,artist_genre_lists,expected",
    [
        # согласие трека и артиста -> берём фактический (гранулярно по треку)
        ("punk", [["rock", "punk"]], "punk"),
        # конфликт: зонтичный альбомный тег ("rock" в GENERIC_SLUGS) -> доверяем артисту
        # (кейс New Politics: альбом стоит "rock", у артиста только "indie")
        ("rock", [["indie"]], "indie"),
        # конфликт: точный альбомный тег (не в GENERIC_SLUGS) -> доверяем треку, даже если
        # у артиста другой основной жанр (настоящий эксперимент артиста в ином жанре)
        ("dnb", [["indie"]], "electronics"),
        # пустой genre_raw -> едем по артисту
        (None, [["indie"]], "indie"),
        ("", [["indie"]], "indie"),
        # у артиста нет тегов -> едем по треку (genre_raw "rock" резолвится в корень "allrock")
        ("rock", [[]], "allrock"),
        # несколько артистов на треке -> голосование dominant по объединённым тегам
        ("rock", [["indie"], ["indie", "metal"]], "indie"),
        # ничего не помогло
        (None, [[]], "other"),
    ],
)
def test_classify_track(catalog, genre_raw, artist_genre_lists, expected):
    assert genres.classify_track(genre_raw, artist_genre_lists, catalog) == expected

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from yandex_music import Client, Genre

from .ymclient import with_retries

GENRE_CATALOG_FILE = "genre_catalog.json"

# Общие "зонтичные" альбомные жанры - сигнал низкой уверенности: Яндекс вешает их на
# альбом по умолчанию, когда не может/не хочет уточнить жанр. Ровно это и создаёт шум,
# который classify_track чинит через жанры артиста.
GENERIC_SLUGS = {
    "rock",
    "alternative",
    "indie",
    "pop",
    "electronics",
    "dance",
    "metal",
    "rap",
    "jazz",
    "folk",
}

# Корневые жанры каталога Яндекс.Музыки -> наши крупные корзины.
# Таблица построена по реальному дереву client.genres() (все 34 актуальных корня на момент
# написания), а не по предположениям об именах слагов — проверено на живом каталоге
# (cache/genre_catalog.json). Если Яндекс добавит новый корневой жанр, он попадёт в "other" —
# смотрите разбивку "other" в выводе команды report, чтобы дополнить таблицу.
ROOT_BUCKET: dict[str, str] = {
    # рок
    "allrock": "rock",
    # инди / альтернатива / панк
    "alternative": "indie-alt",
    "indie": "indie-alt",
    "punk": "indie-alt",
    # метал
    "metal": "metal",
    # рэп
    "rap": "rap",
    # электроника / танцевальная
    "electronics": "electronic",
    "dance": "electronic",
    # джаз и блюз
    "jazz": "jazz-blues",
    "blues": "jazz-blues",
    # классика
    "classicalmusic": "classical",
    # поп
    "pop": "pop",
    "estrada": "pop",
    "rnb": "pop",
    # фолк и world
    "folk": "folk-world",
    "folkgenre": "folk-world",
    "bard": "folk-world",
    "shanson": "folk-world",
    "country": "folk-world",
    "reggae": "folk-world",
    "ska": "folk-world",
    "islamicgenre": "folk-world",
    # саундтреки
    "soundtrack": "soundtrack",
    # не музыка / нераспределяемое -> "other"
    "all": "other",
    "other": "other",
    "relax": "other",
    "children": "other",
    "forchildren": "other",
    "poemsforchildren": "other",
    "fairytales": "other",
    "audiobooks": "other",
    "booksnotinrussian": "other",
    "fiction": "other",
    "nonfictionliterature": "other",
    "podcasts": "other",
    "naturesounds": "other",
}


def flatten_catalog(roots: list[Genre]) -> dict[str, dict]:
    """id жанра/поджанра -> {title, root_id}."""
    flat: dict[str, dict] = {}

    def walk(genre: Genre, root_id: str) -> None:
        flat[genre.id] = {"title": genre.title, "root_id": root_id}
        for sub in genre.sub_genres:
            walk(sub, root_id)

    for root in roots:
        walk(root, root.id)

    return flat


def load_or_fetch_catalog(client: Client, cache_dir: Path) -> dict[str, dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / GENRE_CATALOG_FILE
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    roots = with_retries(lambda: client.genres())
    flat = flatten_catalog(roots)
    cache_file.write_text(json.dumps(flat, ensure_ascii=False, indent=2), encoding="utf-8")
    return flat


def fine_of(slug: str | None, catalog: dict[str, dict]) -> str | None:
    """Слаг жанра (любой глубины) -> id корневого жанра ("тонкая" под-жанровая классификация)."""
    if not slug:
        return None
    entry = catalog.get(slug)
    return entry["root_id"] if entry else slug


def coarse_of(fine: str | None) -> str:
    """Корневой жанр -> одна из 11 крупных корзин ("грубая" классификация)."""
    if not fine:
        return "other"
    return ROOT_BUCKET.get(fine, "other")


def bucket_for(genre_raw: str | None, catalog: dict[str, dict]) -> str:
    return coarse_of(fine_of(genre_raw, catalog))


def dominant(fines: list[str]) -> str | None:
    """Самый частый элемент; при равенстве частот - первый по порядку появления."""
    if not fines:
        return None
    return Counter(fines).most_common(1)[0][0]


def classify_track(
    genre_raw: str | None,
    artist_genre_lists: list[list[str]],
    catalog: dict[str, dict],
) -> str:
    """Сводит жанр трека (альбома) и жанры его артиста(ов) в один под-жанр (root_id).

    Args:
        genre_raw: жанр альбома трека.
        artist_genre_lists: список списков жанровых слагов - один список на артиста трека,
            в порядке артистов (первый - главный).
        catalog: плоский каталог жанров (см. load_or_fetch_catalog).

    Returns:
        root_id под-жанра ("punk", "indie", "allrock", ...) или "other".
    """
    track_fine = fine_of(genre_raw, catalog)

    artist_fines: list[str] = []
    for genre_list in artist_genre_lists:
        for slug in genre_list:
            fine = fine_of(slug, catalog)
            if fine:
                artist_fines.append(fine)

    if not track_fine:
        return dominant(artist_fines) or "other"
    if not artist_fines:
        return track_fine
    if track_fine in artist_fines:
        return track_fine
    if genre_raw in GENERIC_SLUGS:
        return dominant(artist_fines)
    return track_fine

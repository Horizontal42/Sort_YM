from __future__ import annotations

import json
from pathlib import Path

from yandex_music import Client, Genre

from .ymclient import with_retries

GENRE_CATALOG_FILE = "genre_catalog.json"

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


def bucket_for(genre_raw: str | None, catalog: dict[str, dict]) -> str:
    if not genre_raw:
        return "other"
    entry = catalog.get(genre_raw)
    root_id = entry["root_id"] if entry else genre_raw
    return ROOT_BUCKET.get(root_id, "other")

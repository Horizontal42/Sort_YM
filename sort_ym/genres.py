from __future__ import annotations

import json
from pathlib import Path

from yandex_music import Client, Genre

GENRE_CATALOG_FILE = "genre_catalog.json"

# Корневые жанры каталога Яндекс.Музыки -> наши крупные корзины.
# Список получен из реального дерева client.genres() и может дополняться:
# если жанр трека не находится ни в одном известном корне, он попадает в "other" —
# смотрите разбивку "other" в выводе команды report, чтобы дополнить таблицу.
ROOT_BUCKET: dict[str, str] = {
    "pop": "pop",
    "ruspop": "pop",
    "estrada": "pop",
    "rnb": "pop",
    "disco": "pop",
    "rock": "rock",
    "rusrock": "rock",
    "hardrock": "rock",
    "prog": "rock",
    "alternative": "indie-alt",
    "indie": "indie-alt",
    "punk": "indie-alt",
    "postrock": "indie-alt",
    "metal": "metal",
    "extreme": "metal",
    "industrial": "metal",
    "rap": "rap",
    "rusrap": "rap",
    "hip": "rap",
    "hiphop": "rap",
    "trap": "rap",
    "electronics": "electronic",
    "dance": "electronic",
    "house": "electronic",
    "techno": "electronic",
    "trance": "electronic",
    "dnb": "electronic",
    "dubstep": "electronic",
    "jazz": "jazz-blues",
    "blues": "jazz-blues",
    "soul": "jazz-blues",
    "funk": "jazz-blues",
    "classicalmusic": "classical",
    "classical": "classical",
    "opera": "classical",
    "folk": "folk-world",
    "bard": "folk-world",
    "author": "folk-world",
    "avtorskaya": "folk-world",
    "shanson": "folk-world",
    "world": "folk-world",
    "reggae": "folk-world",
    "country": "folk-world",
    "films": "soundtrack",
    "soundtrack": "soundtrack",
    "musical": "soundtrack",
    "cartoon": "soundtrack",
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

    roots = client.genres()
    flat = flatten_catalog(roots)
    cache_file.write_text(json.dumps(flat, ensure_ascii=False, indent=2), encoding="utf-8")
    return flat


def bucket_for(genre_raw: str | None, catalog: dict[str, dict]) -> str:
    if not genre_raw:
        return "other"
    entry = catalog.get(genre_raw)
    root_id = entry["root_id"] if entry else genre_raw
    return ROOT_BUCKET.get(root_id, "other")

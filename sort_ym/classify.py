from __future__ import annotations

# Крупные корзины (11 штук) - используются, когда под-жанровая группа слишком мала
# и схлопывается в родителя (см. report.build_rows).
BUCKET_LABELS: dict[str, str] = {
    "pop": "Поп",
    "rock": "Рок",
    "metal": "Метал",
    "rap": "Рэп",
    "electronic": "Электроника",
    "jazz-blues": "Джаз и блюз",
    "classical": "Классика",
    "folk-world": "Фолк и world",
    "indie-alt": "Инди и альтернатива",
    "soundtrack": "Саундтреки",
    "other": "Разное",
}

# Под-жанры (root_id из реального дерева client.genres()) - используются, когда группа
# достаточно большая, чтобы получить отдельный плейлист (см. config.small_group_min).
FINE_LABELS: dict[str, str] = {
    "allrock": "Рок",
    "alternative": "Альтернатива",
    "indie": "Инди",
    "punk": "Панк",
    "metal": "Метал",
    "rap": "Рэп",
    "electronics": "Электроника",
    "dance": "Танцевальная",
    "jazz": "Джаз",
    "blues": "Блюз",
    "classicalmusic": "Классика",
    "pop": "Поп",
    "estrada": "Эстрада",
    "rnb": "R&B",
    "folk": "Музыка мира",
    "folkgenre": "Фолк",
    "bard": "Авторская песня",
    "shanson": "Шансон",
    "country": "Кантри",
    "reggae": "Регги",
    "ska": "Ска",
    "islamicgenre": "Исламская музыка",
    "soundtrack": "Саундтреки",
    "all": "Микс",
    "other": "Разное",
    "relax": "Лёгкая музыка",
    "children": "Детская музыка",
    "forchildren": "Детская",
    "poemsforchildren": "Стихи для детей",
    "fairytales": "Аудиосказки",
    "audiobooks": "Разговорное",
    "booksnotinrussian": "Аудиокниги на ин. языке",
    "fiction": "Художественная литература",
    "nonfictionliterature": "Нон-фикшн",
    "podcasts": "Подкасты",
    "naturesounds": "Звуки природы",
}

_ALL_LABELS: dict[str, str] = {**FINE_LABELS, **BUCKET_LABELS}

LANG_LABELS: dict[str, str] = {
    "RU": "RU",
    "INT": "INT",
    "UNKNOWN": "Не определено",
}


def playlist_name(bucket: str, lang: str) -> str:
    """bucket - либо под-жанр (root_id), либо крупная корзина (после схлопывания)."""
    bucket_label = _ALL_LABELS.get(bucket, BUCKET_LABELS["other"])
    lang_label = LANG_LABELS.get(lang, LANG_LABELS["UNKNOWN"])
    return f"{bucket_label} — {lang_label}"

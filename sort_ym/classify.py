from __future__ import annotations

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

LANG_LABELS: dict[str, str] = {
    "RU": "RU",
    "INT": "INT",
    "UNKNOWN": "Не определено",
}


def playlist_name(bucket: str, lang: str) -> str:
    bucket_label = BUCKET_LABELS.get(bucket, BUCKET_LABELS["other"])
    lang_label = LANG_LABELS.get(lang, LANG_LABELS["UNKNOWN"])
    return f"{bucket_label} — {lang_label}"

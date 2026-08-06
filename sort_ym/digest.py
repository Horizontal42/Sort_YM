from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path

from . import classify, genres, report

DIGEST_FILE = "digest.md"

DECADE_UNKNOWN = "unknown"
DECADE_MIN_YEAR = 1900
DECADE_MAX_YEAR = 2100
DECADE_TOP_GENRES = 3  # константа вёрстки (сколько жанров показывать на десятилетие), не config-knob


def _by_track_key(tracks_cache: dict[str, dict]) -> dict[tuple, dict]:
    """(id, album_id) из ЗНАЧЕНИЙ кэша -> сама запись кэша.

    Ключ tracks_cache - исходный id из likes.tracks_ids, а не f"{id}:{album_id}" (у треков без
    альбома это разные строки), поэтому склейка со строками report.build_rows идёт по значениям.
    """
    return {(t["id"], t["album_id"]): t for t in tracks_cache.values()}


def _most_common_deterministic(counter: Counter):
    """Самое частое значение; при равенстве частот - детерминированный тай-брейк по значению."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _artist_ids_by_name(tracks_cache: dict[str, dict]) -> dict[str, list[str]]:
    """Имя артиста -> id (в порядке первого появления, без дублей).

    fetch._serialize кладёт в artists всех артистов с именем, а в artist_ids - только тех, у кого
    есть и имя, и id, поэтому списки могут расходиться по длине для одного трека. Берём только
    треки, где длины совпадают - иначе zip присвоил бы имени чужой id. Имя, встречающееся только
    в рассинхронных треках, остаётся без id (и без тегов) - лучше пусто, чем неверно.
    """
    ids_by_name: dict[str, list[str]] = {}
    for t in tracks_cache.values():
        artists = t["artists"]
        artist_ids = t["artist_ids"]
        if len(artists) != len(artist_ids):
            continue
        for name, aid in zip(artists, artist_ids):
            ids = ids_by_name.setdefault(name, [])
            sid = str(aid)
            if sid not in ids:
                ids.append(sid)
    return ids_by_name


def artist_tags(
    name: str,
    ids_by_name: dict[str, list[str]],
    artist_genres: dict[str, dict],
    limit: int = 3,
) -> list[str]:
    """Собственные жанровые слаги артиста (объединение по всем безопасно найденным id)."""
    tags: list[str] = []
    for aid in ids_by_name.get(name, []):
        entry = artist_genres.get(aid)
        if not entry:
            continue
        for tag in entry.get("genres", []):
            if tag not in tags:
                tags.append(tag)
    return tags[:limit]


def artist_stats(
    rows: list[dict],
    tracks_cache: dict[str, dict],
    artist_genres: dict[str, dict],
) -> list[dict]:
    """[{"name", "tracks", "top_fine", "tags"}], сортировка: tracks desc, затем name.

    Считает по ИМЕНИ артиста, а не через zip(artists, artist_ids) - списки не всегда выровнены.
    top_fine - самый частый fine_bucket среди треков этого исполнителя.
    """
    by_key = _by_track_key(tracks_cache)
    ids_by_name = _artist_ids_by_name(tracks_cache)

    counts: dict[str, int] = {}
    fines: dict[str, Counter] = {}
    for row in rows:
        t = by_key.get((row["id"], row["album_id"]))
        if t is None:
            continue
        for name in t["artists"]:
            counts[name] = counts.get(name, 0) + 1
            fines.setdefault(name, Counter())[row["fine_bucket"]] += 1

    result = [
        {
            "name": name,
            "tracks": tracks,
            "top_fine": fines[name].most_common(1)[0][0],
            "tags": artist_tags(name, ids_by_name, artist_genres),
        }
        for name, tracks in counts.items()
    ]
    result.sort(key=lambda a: (-a["tracks"], a["name"]))
    return result


def genre_stats(rows: list[dict]) -> list[dict]:
    """[{"bucket", "tracks", "langs"}], максимум 11 строк (число крупных корзин).

    bucket = genres.coarse_of(row["fine_bucket"]), а не row["bucket"] - оно смешивает под-жанр
    и крупную корзину после схлопывания мелких групп в report.build_rows.
    """
    counts: dict[str, int] = {}
    langs: dict[str, Counter] = {}
    for row in rows:
        bucket = genres.coarse_of(row["fine_bucket"])
        counts[bucket] = counts.get(bucket, 0) + 1
        langs.setdefault(bucket, Counter())[row["lang"]] += 1

    result = [{"bucket": b, "tracks": n, "langs": dict(langs[b])} for b, n in counts.items()]
    result.sort(key=lambda g: (-g["tracks"], g["bucket"]))
    return result


def fine_stats(rows: list[dict]) -> list[dict]:
    """[{"fine", "tracks"}], максимум ~34 строки (размер genres.ROOT_BUCKET)."""
    counts = Counter(row["fine_bucket"] for row in rows)
    result = [{"fine": f, "tracks": n} for f, n in counts.items()]
    result.sort(key=lambda g: (-g["tracks"], g["fine"]))
    return result


def lang_stats(rows: list[dict]) -> dict[str, int]:
    return dict(Counter(row["lang"] for row in rows))


def decade_key(year) -> str:
    """Год -> "1990"/"2010"/... или DECADE_UNKNOWN (None, не int, либо вне разумных границ)."""
    if not isinstance(year, int) or year < DECADE_MIN_YEAR or year > DECADE_MAX_YEAR:
        return DECADE_UNKNOWN
    return str((year // 10) * 10)


def decade_label(key: str) -> str:
    return "Неизвестно" if key == DECADE_UNKNOWN else f"{key}-е"


def decade_stats(rows: list[dict], tracks_cache: dict[str, dict]) -> list[dict]:
    """[{"key", "tracks", "top_genres"}], сортировка по году desc, "Неизвестно" последним.

    top_genres - топ-DECADE_TOP_GENRES крупных корзин десятилетия (не полная матрица жанр x
    десятилетие - она была бы до 11 x ~13 строк).
    """
    by_key = _by_track_key(tracks_cache)

    counts: dict[str, int] = {}
    genre_counts: dict[str, Counter] = {}
    for row in rows:
        t = by_key.get((row["id"], row["album_id"]))
        year = t.get("year") if t else None
        key = decade_key(year)
        counts[key] = counts.get(key, 0) + 1
        bucket = genres.coarse_of(row["fine_bucket"])
        genre_counts.setdefault(key, Counter())[bucket] += 1

    result = [
        {
            "key": key,
            "tracks": n,
            "top_genres": [
                {"bucket": b, "tracks": c}
                for b, c in genre_counts[key].most_common(DECADE_TOP_GENRES)
            ],
        }
        for key, n in counts.items()
    ]
    result.sort(key=lambda d: (d["key"] == DECADE_UNKNOWN, -int(d["key"]) if d["key"] != DECADE_UNKNOWN else 0))
    return result


def album_stats(tracks_cache: dict[str, dict]) -> list[dict]:
    """[{"album_id", "title", "year", "artists", "tracks"}], сортировка tracks desc, затем title.

    Треки с album_id is None (сторонние загрузки без привязки к альбому) пропускаются - они не
    участвуют в подсчёте "альбом vs синглы", но остаются во всех остальных срезах.
    title/year/artists представителя альбома - самое частое непустое значение среди его треков
    (детерминированный тай-брейк), а не "первое попавшееся".
    """
    groups: dict[int, list[dict]] = {}
    for t in tracks_cache.values():
        album_id = t.get("album_id")
        if album_id is None:
            continue
        groups.setdefault(album_id, []).append(t)

    result = []
    for album_id, tracks in groups.items():
        titles = Counter(t["album_title"] for t in tracks if t.get("album_title"))
        title = _most_common_deterministic(titles) if titles else f"без названия (#{album_id})"
        years = Counter(t["year"] for t in tracks if t.get("year") is not None)
        year = _most_common_deterministic(years) if years else None
        artist_tuples = Counter(tuple(t["artists"]) for t in tracks)
        artists = ", ".join(_most_common_deterministic(artist_tuples)) if artist_tuples else ""
        result.append(
            {
                "album_id": album_id,
                "title": title,
                "year": year,
                "artists": artists,
                "tracks": len(tracks),
            }
        )
    result.sort(key=lambda a: (-a["tracks"], a["title"]))
    return result


def _pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


def render_digest(
    rows: list[dict],
    tracks_cache: dict[str, dict],
    artist_genres: dict[str, dict],
    top_artists: int,
    top_albums: int,
) -> str:
    total = len(rows)
    unique_artists = {name for t in tracks_cache.values() for name in t["artists"]}
    genre_rows = genre_stats(rows)
    fine_rows = fine_stats(rows)
    lang_rows = lang_stats(rows)
    decade_rows = decade_stats(rows, tracks_cache)
    artists = artist_stats(rows, tracks_cache, artist_genres)
    albums = album_stats(tracks_cache)
    other = report.other_breakdown(rows)

    known_years = sorted(t["year"] for t in tracks_cache.values() if t.get("year") is not None)

    lines: list[str] = ["# Дайджест музыкальной библиотеки", "", "## Итоги"]
    lines.append(f"- Лайкнутых треков: {total}")
    lines.append(f"- Уникальных исполнителей: {len(unique_artists)}")
    lines.append(
        f"- Задействовано крупных корзин: {len(genre_rows)} из {len(classify.BUCKET_LABELS)}, "
        f"под-жанров: {len(fine_rows)}"
    )
    if known_years:
        median_year = round(statistics.median(known_years))
        lines.append(
            f"- Год релиза: медиана {median_year}, известен у {len(known_years)} из {total} "
            f"({_pct(len(known_years), total)}%)"
        )
    else:
        lines.append(
            "> Годы релиза и названия альбомов ещё не загружены - запустите `python -m sort_ym "
            "fetch` (кэш треков обновится один раз). Секции «Десятилетия» и «Топ альбомов» "
            "пока неинформативны."
        )
    lines.append("")

    lines.append("## Жанры (крупные корзины)")
    for g in genre_rows:
        label = classify.BUCKET_LABELS.get(g["bucket"], g["bucket"])
        lang_parts = [
            f"{classify.LANG_LABELS.get(code, code)} {n}"
            for code, n in sorted(g["langs"].items(), key=lambda kv: -kv[1])
        ]
        lines.append(f"- {label} — {g['tracks']} ({_pct(g['tracks'], total)}%): {' / '.join(lang_parts)}")
    lines.append("")

    lines.append("## Под-жанры")
    for f in fine_rows:
        label = classify.FINE_LABELS.get(f["fine"], f["fine"])
        lines.append(f"- {label} — {f['tracks']}")
    lines.append("")

    lines.append("## Язык")
    for code, n in sorted(lang_rows.items(), key=lambda kv: -kv[1]):
        label = classify.LANG_LABELS.get(code, code)
        lines.append(f"- {label}: {n} ({_pct(n, total)}%)")
    lines.append("")

    lines.append("## Десятилетия")
    lines.append("В скобках — доля от библиотеки; далее — три самые частые крупные корзины десятилетия.")
    for d in decade_rows:
        label = decade_label(d["key"])
        top_genres_str = ", ".join(
            f"{classify.BUCKET_LABELS.get(tg['bucket'], tg['bucket'])} {tg['tracks']}"
            for tg in d["top_genres"]
        )
        lines.append(f"- {label} — {d['tracks']} ({_pct(d['tracks'], total)}%): {top_genres_str}")
    lines.append("")

    shown_artists = artists[:top_artists]
    rest_artists = artists[top_artists:]
    lines.append(f"## Топ-{len(shown_artists)} исполнителей")
    lines.append("Счётчик — упоминания в треках (у трека может быть несколько исполнителей).")
    lines.append("В скобках — самый частый под-жанр исполнителя, затем его собственные теги из каталога.")
    for i, a in enumerate(shown_artists, 1):
        fine_label = classify.FINE_LABELS.get(a["top_fine"], a["top_fine"])
        tag_part = f"; {', '.join(a['tags'])}" if a["tags"] else ""
        lines.append(f"{i}. {a['name']} — {a['tracks']} ({fine_label}{tag_part})")
    if rest_artists:
        rest_tracks = sum(a["tracks"] for a in rest_artists)
        one_track = sum(1 for a in rest_artists if a["tracks"] == 1)
        lines.append("")
        lines.append(
            f"Ещё {len(rest_artists)} исполнителей с {rest_artists[-1]['tracks']}-"
            f"{rest_artists[0]['tracks']} треками, {rest_tracks} упоминаний суммарно; "
            f"из них {one_track} — по одному треку."
        )
    lines.append("")

    shown_albums = albums[:top_albums]
    rest_albums = albums[top_albums:]
    lines.append(f"## Топ-{len(shown_albums)} альбомов")
    lines.append("Счётчик — сколько треков с альбома лайкнуто.")
    for i, alb in enumerate(shown_albums, 1):
        year_part = f" ({alb['year']})" if alb["year"] else ""
        lines.append(f"{i}. {alb['artists']} — {alb['title']}{year_part} — {alb['tracks']}")
    if rest_albums:
        deep_tracks = sum(a["tracks"] for a in albums if a["tracks"] >= 2)
        lines.append("")
        lines.append(
            f"Ещё {len(rest_albums)} альбомов с {rest_albums[-1]['tracks']}-"
            f"{rest_albums[0]['tracks']} лайкнутыми треками. Треков с альбомов, где лайкнуто "
            f"2 и более: {deep_tracks} из {total} ({_pct(deep_tracks, total)}%)."
        )
    lines.append("")

    if other:
        lines.append("## Разное (нераспознанные сырые жанры)")
        for genre_raw, n in sorted(other.items(), key=lambda kv: -kv[1])[:5]:
            lines.append(f"- {genre_raw}: {n}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_digest(text: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / DIGEST_FILE
    out_file.write_text(text, encoding="utf-8")
    return out_file

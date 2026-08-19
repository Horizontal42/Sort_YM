from __future__ import annotations

import argparse
from typing import NamedTuple

from yandex_music import Client
from yandex_music.exceptions import UnauthorizedError

from . import apply as apply_mod
from . import analyze, auth, classify, digest, fetch, genres, language, lyrics, report, source
from .config import Config, load_config
from .ymclient import make_client


SOURCE_HELP = (
    "ссылка на плейлист Яндекс.Музыки (https://music.yandex.ru/users/<логин>/playlists/<номер>) - "
    "анализировать его вместо своих лайков; данные загружаются заново при каждом запуске и не кэшируются"
)
LABEL_HELP = (
    "метка источника: треки лягут в отдельные плейлисты «Жанр — RU (метка)» вместо общих "
    "(имеет смысл только вместе с --source)"
)


class _SourceContext(NamedTuple):
    client: Client
    info: source.SourceInfo
    tracks: dict[str, dict]
    artist_genres: dict[str, dict]
    catalog: dict[str, dict]
    lang_cache: dict[str, str | None]


def _source_context(cfg: Config, url: str) -> _SourceContext:
    try:
        source.parse_playlist_url(url)  # быстрый провал до токена и сети
    except source.SourceError as e:
        raise SystemExit(str(e))

    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)

    try:
        data = source.load_source(client, url, cfg.batch_size, cfg.fetch_batch_delay)
    except source.SourceError as e:
        raise SystemExit(str(e))

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)  # общий cache/genre_catalog.json
    lang_cache = language.load_lang_cache(cfg.cache_dir)  # только чтение, без сети - см. ARCHITECTURE

    print(f"Источник: «{data.info.title}» ({data.info.owner}), треков: {len(data.tracks)}")
    return _SourceContext(client, data.info, data.tracks, data.artist_genres, catalog, lang_cache)


def cmd_auth(args: argparse.Namespace) -> None:
    cfg = load_config()
    auth.device_login(cfg.token_file)


def cmd_fetch(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)
    fetch.fetch_liked_tracks(client, cfg.cache_dir, cfg.batch_size, cfg.fetch_batch_delay)
    fetch.fetch_artist_genres(client, cfg.cache_dir, cfg.batch_size, cfg.fetch_batch_delay)


def cmd_lyrics(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    lang_cache: dict[str, str | None] = {}
    if not args.all_languages:
        # Тот же вызов, что в cmd_report: инкрементальный, на заполненном кэше почти no-op,
        # но без него RU-гейт опирался бы только на алфавитную эвристику.
        ids_needing_lang = [str(t["id"]) for t in tracks_cache.values() if t["lyrics_available"]]
        lang_cache = language.fetch_api_languages(client, ids_needing_lang, cfg.cache_dir, cfg.lyrics_request_delay)

    ids = lyrics.ru_lyric_track_ids(tracks_cache, lang_cache, all_languages=args.all_languages)
    if args.limit is not None:
        ids = ids[: args.limit]

    label = "треков" if args.all_languages else "RU-треков"
    print(f"{label} с текстом: {len(ids)}")
    lyrics.fetch_lyrics_text(client, ids, cfg.cache_dir, cfg.lyrics_request_delay)


def cmd_analyze(args: argparse.Namespace) -> None:
    # Ни одной сетевой ручки Яндекса: analyze работает только по кэшам плюс локальная Ollama.
    cfg = load_config()

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    lyrics_cache = lyrics.load_lyrics_cache(cfg.cache_dir)
    if not lyrics_cache:
        raise SystemExit("Нет текстов песен. Сначала запустите: python -m sort_ym lyrics")

    settings = analyze.OllamaSettings(
        host=cfg.ollama_host,
        model=args.model or cfg.ollama_model,
        prompt_version=cfg.ollama_prompt_version,
        timeout=cfg.ollama_timeout,
        keep_alive=cfg.ollama_keep_alive,
    )
    result = analyze.analyze_tracks(tracks_cache, lyrics_cache, cfg.cache_dir, settings, limit=args.limit)
    print(f"\nРазобрано треков в кэше: {len(digest.analyzed_entries(result))}")
    print("Дайджест разбора соберётся при следующем: python -m sort_ym digest")


def _print_report_summary(rows: list[dict], out_file) -> None:
    print("\nРаспределение по плейлистам:")
    for name, n in sorted(report.summarize(rows).items()):
        print(f"  {name}: {n}")

    other = report.other_breakdown(rows)
    if other:
        print("\nНе распознанные жанры (попали в 'Разное'), можно дополнить sort_ym/genres.py:")
        for genre_raw, n in sorted(other.items(), key=lambda kv: -kv[1]):
            print(f"  {genre_raw}: {n}")

    print(f"\nОтчёт сохранён: {out_file}")


def _report_extra_columns(args: argparse.Namespace) -> list[str] | None:
    # --extra - сразу все группы; отдельные --timestamp/--duration/... - точечный выбор,
    # можно сочетать друг с другом (--timestamp --album), --extra их всех перекрывает.
    if args.extra:
        return report.resolve_extra_columns(["all"])
    selected = [name for name in report.EXTRA_GROUPS if getattr(args, name)]
    return report.resolve_extra_columns(selected) if selected else None


def cmd_report(args: argparse.Namespace) -> None:
    cfg = load_config()
    extra_columns = _report_extra_columns(args)

    if args.source:
        ctx = _source_context(cfg, args.source)
        rows = report.build_rows(
            ctx.tracks, ctx.lang_cache, ctx.catalog, ctx.artist_genres, cfg.small_group_min,
            order=args.order, extra_columns=extra_columns,
        )
        out_file = report.write_report(rows, cfg.out_dir, report.REPORT_SOURCE_FILE, extra_columns=extra_columns)
        _print_report_summary(rows, out_file)
        return

    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)
    artist_genres = fetch.load_artist_genres(cfg.cache_dir)

    ids_needing_lang = [str(t["id"]) for t in tracks_cache.values() if t["lyrics_available"]]
    lang_cache = language.fetch_api_languages(client, ids_needing_lang, cfg.cache_dir, cfg.lyrics_request_delay)

    rows = report.build_rows(
        tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min,
        order=args.order, extra_columns=extra_columns,
    )
    out_file = report.write_report(rows, cfg.out_dir, extra_columns=extra_columns)
    _print_report_summary(rows, out_file)


def cmd_apply(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Это изменит ваш аккаунт. Добавьте флаг --yes для подтверждения.")

    label = None
    if args.label is not None:
        if not args.source:
            raise SystemExit(
                "--label имеет смысл только вместе с --source: метка нужна, чтобы отделить "
                "треки из чужого плейлиста от ваших собственных."
            )
        label = args.label.strip()
        if not label:
            raise SystemExit("--label не может быть пустым.")

    cfg = load_config()

    if args.source:
        ctx = _source_context(cfg, args.source)
        rows = report.build_rows(ctx.tracks, ctx.lang_cache, ctx.catalog, ctx.artist_genres, cfg.small_group_min)
        if label:
            for row in rows:
                row["target_playlist"] = classify.with_label(row["target_playlist"], label)
        print("Целевые плейлисты: " + (f"отдельные, с меткой «{label}»" if label else "общие (как для лайков)"))
        apply_mod.apply_classification(ctx.client, rows, cfg.apply_request_delay, limit=args.limit)
        return

    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)

    tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
    if not tracks_cache:
        raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

    catalog = genres.load_or_fetch_catalog(client, cfg.cache_dir)
    artist_genres = fetch.load_artist_genres(cfg.cache_dir)
    ids_needing_lang = [str(t["id"]) for t in tracks_cache.values() if t["lyrics_available"]]
    lang_cache = language.fetch_api_languages(client, ids_needing_lang, cfg.cache_dir, cfg.lyrics_request_delay)
    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)

    apply_mod.apply_classification(client, rows, cfg.apply_request_delay, limit=args.limit)


def cmd_digest(args: argparse.Namespace) -> None:
    cfg = load_config()

    if args.source:
        ctx = _source_context(cfg, args.source)
        tracks_cache, artist_genres, catalog, lang_cache = ctx.tracks, ctx.artist_genres, ctx.catalog, ctx.lang_cache
        wording = digest.playlist_wording(ctx.info.title, ctx.info.owner, ctx.info.url)
        out_name = digest.DIGEST_SOURCE_FILE
        analysis = {}
    else:
        tracks_cache = fetch.load_tracks_cache(cfg.cache_dir)
        if not tracks_cache:
            raise SystemExit("Кэш треков пуст. Сначала запустите: python -m sort_ym fetch")

        catalog = genres.load_catalog(cfg.cache_dir)
        if not catalog:
            raise SystemExit("Нет снимка дерева жанров. Сначала запустите: python -m sort_ym report")

        artist_genres = fetch.load_artist_genres(cfg.cache_dir)
        lang_cache = language.load_lang_cache(cfg.cache_dir)  # только кэш, без сети
        wording, out_name = digest.DEFAULT_WORDING, digest.DIGEST_FILE
        analysis = analyze.load_analysis(cfg.cache_dir)  # только кэш, без сети и без Ollama

    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)

    top = args.top if args.top is not None else cfg.digest_top_artists
    top_albums = args.top_albums if args.top_albums is not None else cfg.digest_top_albums
    text = digest.render_digest(rows, tracks_cache, artist_genres, top, top_albums, wording=wording, analysis=analysis)
    out_file = digest.write_digest(text, cfg.out_dir, out_name)

    if analysis:
        lyrics_text = digest.render_lyrics_digest(tracks_cache, analysis)
        lyrics_file = digest.write_digest(lyrics_text, cfg.out_dir, digest.LYRICS_DIGEST_FILE)
        print(f"Разбор текстов сохранён: {lyrics_file}")

    print("\nЖанры:")
    for g in digest.genre_stats(rows):
        print(f"  {classify.BUCKET_LABELS.get(g['bucket'], g['bucket'])}: {g['tracks']}")

    print(f"\nДайджест сохранён: {out_file}")


def cmd_dedupe(args: argparse.Namespace) -> None:
    cfg = load_config()
    client = make_client(auth.get_token(cfg.token_file), cfg.request_timeout)
    apply_mod.dedupe_playlists(client, cfg.apply_request_delay, dry_run=not args.yes)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sort_ym", description="Сортировка лайкнутых треков Яндекс.Музыки по жанру и языку")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="войти через device-flow и сохранить токен")
    sub.add_parser("fetch", help="загрузить лайкнутые треки в локальный кэш")

    p_lyrics = sub.add_parser("lyrics", help="загрузить тексты песен RU-треков в cache/lyrics_text.json")
    p_lyrics.add_argument("--limit", type=int, default=None, help="ограничить количество треков (для пробного запуска)")
    p_lyrics.add_argument(
        "--all-languages",
        action="store_true",
        help="не фильтровать по языку - загрузить тексты всех треков с лирикой, а не только RU",
    )

    p_analyze = sub.add_parser(
        "analyze",
        help="разобрать тексты песен локальной моделью через Ollama (cache/lyrics_analysis.json); "
        "долгий локальный прогон, прерывается и продолжается без потери прогресса",
    )
    p_analyze.add_argument("--limit", type=int, default=None, help="ограничить количество треков (для пробного запуска)")
    p_analyze.add_argument("--model", default=None, help="переопределить модель Ollama из config.toml")

    p_report = sub.add_parser("report", help="посчитать распределение по плейлистам и сохранить out/report.csv (ничего не меняет в аккаунте)")
    p_report.add_argument("--source", metavar="URL", default=None, help=SOURCE_HELP)
    p_report.add_argument(
        "--order", choices=["grouped", "playlist"], default="grouped",
        help="grouped (по умолчанию) - сортировка по целевому плейлисту; "
        "playlist - как треки идут в источнике (в лайках или в --source плейлисте), без сортировки",
    )
    p_report.add_argument(
        "--extra", action="store_true",
        help="добавить в CSV все доп. колонки сразу (то же самое, что все флаги ниже вместе)",
    )
    p_report.add_argument("--timestamp", action="store_true", help="+ дата добавления трека (added_at)")
    p_report.add_argument("--duration", action="store_true", help="+ длительность трека (duration_ms)")
    p_report.add_argument("--version", action="store_true", help="+ пометка версии трека/альбома (ремикс, юбилейное издание и т.п.)")
    p_report.add_argument("--album", action="store_true", help="+ дата релиза и лайки альбома (release_date, album_likes_count)")
    p_report.add_argument("--artist", action="store_true", help="+ счётчики и рейтинг первого артиста трека")

    p_apply = sub.add_parser("apply", help="создать плейлисты и добавить треки")
    p_apply.add_argument("--yes", action="store_true", help="подтвердить внесение изменений в аккаунт")
    p_apply.add_argument("--limit", type=int, default=None, help="ограничить количество треков (для пробного запуска)")
    p_apply.add_argument("--source", metavar="URL", default=None, help=SOURCE_HELP)
    p_apply.add_argument("--label", metavar="NAME", default=None, help=LABEL_HELP)

    p_dedupe = sub.add_parser("dedupe", help="найти и убрать повторные вставки одного трека в плейлистах")
    p_dedupe.add_argument("--yes", action="store_true", help="подтвердить удаление дублей (без флага - только отчёт)")

    p_digest = sub.add_parser(
        "digest",
        help="сводка библиотеки (топ-исполнители, жанры, десятилетия, топ-альбомы) в out/digest.md - для вставки в чат с LLM",
    )
    p_digest.add_argument("--top", type=int, default=None, help="сколько исполнителей показать поимённо (по умолчанию из config.toml)")
    p_digest.add_argument("--top-albums", type=int, default=None, help="сколько альбомов показать поимённо (по умолчанию из config.toml)")
    p_digest.add_argument("--source", metavar="URL", default=None, help=SOURCE_HELP)

    args = parser.parse_args(argv)

    commands = {
        "auth": cmd_auth,
        "fetch": cmd_fetch,
        "lyrics": cmd_lyrics,
        "analyze": cmd_analyze,
        "report": cmd_report,
        "apply": cmd_apply,
        "dedupe": cmd_dedupe,
        "digest": cmd_digest,
    }
    try:
        commands[args.command](args)
    except UnauthorizedError:
        raise SystemExit("Яндекс отклонил запрос - токен мог истечь. Выполните: python -m sort_ym auth")


if __name__ == "__main__":
    main()

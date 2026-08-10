from __future__ import annotations

import argparse
from typing import NamedTuple

from yandex_music import Client
from yandex_music.exceptions import UnauthorizedError

from . import apply as apply_mod
from . import auth, classify, digest, fetch, genres, language, report, source
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


def cmd_report(args: argparse.Namespace) -> None:
    cfg = load_config()
    extra_columns = report.resolve_extra_columns(args.extra) if args.extra else None

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
    lang_cache = language.load_lang_cache(cfg.cache_dir)
    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)

    apply_mod.apply_classification(client, rows, cfg.apply_request_delay, limit=args.limit)


def cmd_digest(args: argparse.Namespace) -> None:
    cfg = load_config()

    if args.source:
        ctx = _source_context(cfg, args.source)
        tracks_cache, artist_genres, catalog, lang_cache = ctx.tracks, ctx.artist_genres, ctx.catalog, ctx.lang_cache
        wording = digest.playlist_wording(ctx.info.title, ctx.info.owner, ctx.info.url)
        out_name = digest.DIGEST_SOURCE_FILE
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

    rows = report.build_rows(tracks_cache, lang_cache, catalog, artist_genres, cfg.small_group_min)

    top = args.top if args.top is not None else cfg.digest_top_artists
    top_albums = args.top_albums if args.top_albums is not None else cfg.digest_top_albums
    text = digest.render_digest(rows, tracks_cache, artist_genres, top, top_albums, wording=wording)
    out_file = digest.write_digest(text, cfg.out_dir, out_name)

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

    p_report = sub.add_parser("report", help="посчитать распределение по плейлистам и сохранить out/report.csv (ничего не меняет в аккаунте)")
    p_report.add_argument("--source", metavar="URL", default=None, help=SOURCE_HELP)
    p_report.add_argument(
        "--order", choices=["grouped", "playlist"], default="grouped",
        help="grouped (по умолчанию) - сортировка по целевому плейлисту; "
        "playlist - как треки идут в источнике (в лайках или в --source плейлисте), без сортировки",
    )
    p_report.add_argument(
        "--extra", nargs="+", metavar="GROUP", choices=[*report.EXTRA_GROUPS, "all"], default=None,
        help="добавить в CSV колонки указанных групп (можно несколько через пробел), или 'all' - сразу все: "
        "timestamp (added_at), duration (duration_ms), version (track_version/album_version), "
        "album (release_date/album_likes_count), artist (счётчики и рейтинг первого артиста трека)",
    )

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

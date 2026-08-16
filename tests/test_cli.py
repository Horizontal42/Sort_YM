import pytest

from sort_ym import cli


def test_apply_label_without_source_fails_before_any_network_access():
    with pytest.raises(SystemExit, match="--source"):
        cli.main(["apply", "--yes", "--label", "Друг"])


def test_apply_empty_label_fails_before_any_network_access():
    with pytest.raises(SystemExit, match="пустым"):
        cli.main(["apply", "--yes", "--source", "https://music.yandex.ru/users/a/playlists/1", "--label", "   "])


def test_apply_without_yes_fails_regardless_of_source():
    with pytest.raises(SystemExit, match="--yes"):
        cli.main(["apply"])


def test_lyrics_command_is_wired(monkeypatch):
    called = {}
    monkeypatch.setattr(cli, "cmd_lyrics", lambda args: called.update(limit=args.limit))

    cli.main(["lyrics", "--limit", "5"])

    assert called == {"limit": 5}


def test_analyze_command_is_wired(monkeypatch):
    called = {}
    monkeypatch.setattr(cli, "cmd_analyze", lambda args: called.update(limit=args.limit, model=args.model))

    cli.main(["analyze", "--limit", "3", "--model", "other:latest"])

    assert called == {"limit": 3, "model": "other:latest"}


def test_analyze_defaults_have_no_limit_and_no_model_override(monkeypatch):
    called = {}
    monkeypatch.setattr(cli, "cmd_analyze", lambda args: called.update(limit=args.limit, model=args.model))

    cli.main(["analyze"])

    assert called == {"limit": None, "model": None}

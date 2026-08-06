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

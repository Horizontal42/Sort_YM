import re
from pathlib import Path

from sort_ym import analyze


def test_theme_pattern_accepts_english_snake_case():
    assert re.match(analyze.THEME_PATTERN, "digital_aging")
    assert re.match(analyze.THEME_PATTERN, "modern_loneliness")


def test_theme_pattern_rejects_pilot_failure_modes():
    # Пилот без паттерна давал кириллицу и составные значения через слэш вперемешку
    # с английским в одном прогоне - агрегировать такое невозможно.
    assert not re.match(analyze.THEME_PATTERN, "одиночество")
    assert not re.match(analyze.THEME_PATTERN, "эмоциональное выгорание")
    assert not re.match(analyze.THEME_PATTERN, "Digital_Aging")
    assert not re.match(analyze.THEME_PATTERN, "ethereal/hopeful")
    assert not re.match(analyze.THEME_PATTERN, "ab")


def test_mood_enum_excludes_stance_axis():
    # Смешение осей в пилоте давало "aggressive/triumphant"; ирония/сарказм живут в stance.
    assert "ironic" not in analyze.MOODS
    assert "sarcastic" not in analyze.MOODS
    assert "sincere" not in analyze.MOODS
    assert len(analyze.MOODS) == len(set(analyze.MOODS))


def test_response_schema_constrains_mood_and_themes():
    props = analyze.RESPONSE_SCHEMA["properties"]
    assert props["mood"]["items"]["enum"] == analyze.MOODS
    assert props["mood"]["maxItems"] == 3
    assert props["themes"]["items"]["pattern"] == analyze.THEME_PATTERN
    assert set(analyze.RESPONSE_SCHEMA["required"]) == set(props)


def test_lyrics_hash_changes_with_text():
    assert analyze.lyrics_hash("текст") == analyze.lyrics_hash("текст")
    assert analyze.lyrics_hash("текст") != analyze.lyrics_hash("другой текст")


def test_verify_key_line_accepts_verbatim_quote_ignoring_whitespace_and_case():
    text = "Первая строка\nА я иду, шагаю по Москве\nТретья строка"

    assert analyze.verify_key_line("А я иду, шагаю по Москве", text)
    assert analyze.verify_key_line("а я  иду,  шагаю по москве", text)


def test_verify_key_line_rejects_paraphrase_and_empty():
    text = "А я иду, шагаю по Москве"

    assert not analyze.verify_key_line("Герой идёт по городу", text)
    assert not analyze.verify_key_line("", text)


def test_is_fresh_requires_model_prompt_version_and_hash_match():
    entry = {"model": "m1", "prompt_version": 1, "lyrics_hash": "h1"}

    assert analyze.is_fresh(entry, "m1", 1, "h1")
    assert not analyze.is_fresh(entry, "m2", 1, "h1")
    assert not analyze.is_fresh(entry, "m1", 2, "h1")
    assert not analyze.is_fresh(entry, "m1", 1, "h2")
    assert not analyze.is_fresh(None, "m1", 1, "h1")


def test_is_fresh_false_for_error_marker():
    # Ошибочные записи перезапрашиваются при следующем прогоне - это и есть механизм
    # "повторить упавшие треки" вместо отдельного флага.
    entry = {"model": "m1", "prompt_version": 1, "lyrics_hash": "h1", "error": "TimeoutError: ..."}

    assert not analyze.is_fresh(entry, "m1", 1, "h1")


def test_top_themes_orders_by_frequency_and_limits():
    cache = {
        "1": {"themes": ["loneliness", "city"]},
        "2": {"themes": ["loneliness", "memory"]},
        "3": {"themes": ["loneliness", "city"]},
        "4": {"error": "TimeoutError: ..."},
    }

    assert analyze.top_themes(cache, limit=2) == ["loneliness", "city"]


def test_load_analysis_returns_empty_dict_when_missing(tmp_path: Path):
    assert analyze.load_analysis(tmp_path) == {}

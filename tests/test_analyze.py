import json
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


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _settings(**overrides):
    base = dict(
        host="http://localhost:11434",
        model="qwen3.6-35b-a3b:latest",
        prompt_version=1,
        timeout=600,
        keep_alive="30m",
    )
    base.update(overrides)
    return analyze.OllamaSettings(**base)


def test_call_ollama_sends_schema_constrained_thinking_request(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(
            {"message": {"thinking": "рассуждение", "content": json.dumps({"mood": ["grief"]})}}
        )

    monkeypatch.setattr(analyze.urllib.request, "urlopen", fake_urlopen)

    result = analyze.call_ollama(_settings(), "промпт")

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["timeout"] == 600
    body = captured["body"]
    assert body["model"] == "qwen3.6-35b-a3b:latest"
    assert body["stream"] is False
    assert body["think"] is True
    assert body["format"] == analyze.RESPONSE_SCHEMA
    assert body["keep_alive"] == "30m"
    assert body["options"] == {"num_predict": -1, "temperature": 0.65}
    assert body["messages"] == [{"role": "user", "content": "промпт"}]
    assert result == {"mood": ["grief"]}, "в кэш идёт только content, не thinking"


def test_call_ollama_strips_trailing_slash_from_host(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return FakeResponse({"message": {"content": "{}"}})

    monkeypatch.setattr(analyze.urllib.request, "urlopen", fake_urlopen)

    analyze.call_ollama(_settings(host="http://localhost:11434/"), "промпт")

    assert captured["url"] == "http://localhost:11434/api/chat"


def test_build_prompt_includes_lyrics_title_and_known_themes():
    prompt = analyze.build_prompt("Тоска", ["Артист"], "Текст песни", ["loneliness", "city"])

    assert "Тоска" in prompt
    assert "Артист" in prompt
    assert "Текст песни" in prompt
    assert "loneliness, city" in prompt


def test_build_prompt_omits_known_themes_section_when_empty():
    prompt = analyze.build_prompt("Тоска", ["Артист"], "Текст песни", [])

    assert "Уже использованные темы" not in prompt


GOOD_RESPONSE = {
    "mood": ["melancholy", "longing"],
    "themes": ["modern_loneliness", "city"],
    "emotional_arc": "descent",
    "pov": "confessional",
    "register": "conversational",
    "concreteness": "abstract",
    "stance": "sincere",
    "confidence": 0.9,
    "summary": "Герой бродит по городу.",
    "resonance": "Узнаваемое чувство одиночества.",
    "key_line": "А я иду, шагаю по Москве",
}

TRACKS = {
    "100:10": {"id": 100, "album_id": 10, "title": "Тоска", "artists": ["Артист"]},
    "200:20": {"id": 200, "album_id": 20, "title": "Вторая", "artists": ["Другой"]},
}
LYRICS = {"100": "Первая строка\nА я иду, шагаю по Москве", "200": "Совсем другой текст"}


def test_analyze_stores_metadata_and_verifies_key_line(tmp_path: Path):
    settings = _settings()

    result = analyze.analyze_tracks(
        TRACKS, {"100": LYRICS["100"]}, tmp_path, settings, call=lambda s, p: dict(GOOD_RESPONSE)
    )

    entry = result["100"]
    assert entry["model"] == settings.model
    assert entry["prompt_version"] == 1
    assert entry["lyrics_hash"] == analyze.lyrics_hash(LYRICS["100"])
    assert entry["key_line_verified"] is True
    assert entry["mood"] == ["melancholy", "longing"]
    assert "analyzed_at" in entry
    assert analyze.load_analysis(tmp_path) == result


def test_analyze_marks_paraphrased_key_line_as_unverified(tmp_path: Path):
    response = dict(GOOD_RESPONSE, key_line="Герой идёт по городу")

    result = analyze.analyze_tracks(TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=lambda s, p: response)

    assert result["100"]["key_line_verified"] is False


def test_analyze_writes_after_every_track(tmp_path: Path):
    # Прогон на 266 треках идёт ~3 часа: падение на середине не должно стоить больше
    # одного трека, поэтому запись после каждого, а не пачками.
    def call(settings, prompt):
        if "Вторая" in prompt:
            raise KeyboardInterrupt("пользователь прервал прогон")
        return dict(GOOD_RESPONSE)

    try:
        analyze.analyze_tracks(TRACKS, LYRICS, tmp_path, _settings(), call=call)
    except KeyboardInterrupt:
        pass

    persisted = analyze.load_analysis(tmp_path)
    assert "100" in persisted, "первый трек должен быть на диске несмотря на обрыв на втором"


def test_analyze_records_error_marker_and_continues(tmp_path: Path):
    def call(settings, prompt):
        if "Тоска" in prompt:
            raise TimeoutError("модель зависла")
        return dict(GOOD_RESPONSE)

    result = analyze.analyze_tracks(TRACKS, LYRICS, tmp_path, _settings(), call=call)

    assert "TimeoutError" in result["100"]["error"]
    assert result["200"]["summary"] == "Герой бродит по городу.", "таймаут одного трека не роняет батч"


def test_analyze_retries_error_entries_on_next_run(tmp_path: Path):
    def failing(settings, prompt):
        raise TimeoutError("модель зависла")

    analyze.analyze_tracks(TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=failing)
    result = analyze.analyze_tracks(
        TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=lambda s, p: dict(GOOD_RESPONSE)
    )

    assert "error" not in result["100"]
    assert result["100"]["summary"] == "Герой бродит по городу."


def test_analyze_skips_fresh_entries(tmp_path: Path):
    def boom(settings, prompt):
        raise AssertionError("не должен переанализировать свежую запись")

    analyze.analyze_tracks(TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=lambda s, p: dict(GOOD_RESPONSE))
    result = analyze.analyze_tracks(TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=boom)

    assert result["100"]["summary"] == "Герой бродит по городу."


def test_analyze_reanalyzes_when_lyrics_text_changed(tmp_path: Path):
    analyze.analyze_tracks(TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=lambda s, p: dict(GOOD_RESPONSE))

    updated = dict(GOOD_RESPONSE, summary="Исправленный текст, другой разбор.")
    result = analyze.analyze_tracks(TRACKS, {"100": "Исправленный текст песни"}, tmp_path, _settings(), call=lambda s, p: updated)

    assert result["100"]["summary"] == "Исправленный текст, другой разбор."
    assert result["100"]["lyrics_hash"] == analyze.lyrics_hash("Исправленный текст песни")


def test_analyze_reanalyzes_when_prompt_version_bumped(tmp_path: Path):
    analyze.analyze_tracks(TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(), call=lambda s, p: dict(GOOD_RESPONSE))

    updated = dict(GOOD_RESPONSE, summary="Разбор по новому промпту.")
    result = analyze.analyze_tracks(
        TRACKS, {"100": LYRICS["100"]}, tmp_path, _settings(prompt_version=2), call=lambda s, p: updated
    )

    assert result["100"]["summary"] == "Разбор по новому промпту."
    assert result["100"]["prompt_version"] == 2


def test_analyze_skips_tracks_without_text(tmp_path: Path):
    def boom(settings, prompt):
        raise AssertionError("нечего анализировать у трека без текста")

    result = analyze.analyze_tracks(TRACKS, {"100": None, "200": ""}, tmp_path, _settings(), call=boom)

    assert result == {}


def test_analyze_limit_processes_only_first_n(tmp_path: Path):
    calls = []

    def call(settings, prompt):
        calls.append(prompt)
        return dict(GOOD_RESPONSE)

    analyze.analyze_tracks(TRACKS, LYRICS, tmp_path, _settings(), limit=1, call=call)

    assert len(calls) == 1


def test_analyze_feeds_known_themes_into_later_prompts(tmp_path: Path):
    prompts = []

    def call(settings, prompt):
        prompts.append(prompt)
        return dict(GOOD_RESPONSE)

    analyze.analyze_tracks(TRACKS, LYRICS, tmp_path, _settings(), call=call)

    assert "modern_loneliness" not in prompts[0], "первому треку подмешивать нечего"
    assert "modern_loneliness" in prompts[1], "темы первого трека должны попасть в промпт второго"

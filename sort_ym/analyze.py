from __future__ import annotations

import hashlib
import json
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ANALYSIS_CACHE_FILE = "lyrics_analysis.json"

# Настроение - закрытый список: структурная часть схемы существует ради будущей
# фильтрации/агрегации ("плейлист по настроению"), а свободная строка в пилоте схлопывалась
# в составные значения вроде "aggressive/triumphant". Ирония/сарказм сюда намеренно не входят -
# это ось stance, смешение осей и порождало составные значения.
MOODS = [
    "melancholy",
    "longing",
    "nostalgia",
    "tenderness",
    "sensuality",
    "euphoria",
    "serenity",
    "playfulness",
    "defiance",
    "rage",
    "anxiety",
    "despair",
    "grief",
    "resolve",
]
EMOTIONAL_ARCS = ["static", "descent", "uplift", "turn"]
POVS = ["confessional", "narrative", "abstract", "dialogue"]
REGISTERS = ["poetic", "conversational", "slang", "archaic"]
CONCRETENESS = ["concrete", "mixed", "abstract"]
STANCES = ["sincere", "ironic", "bitter"]

# Темы не закрытый enum (специфичность вроде digital_aging ценна), но язык и формат
# фиксируются схемой: в пилоте без паттерна язык плавал между английским и русским внутри
# одного прогона. Паттерн на уровне JSON Schema делает кириллицу и составные значения
# механически невозможными на этапе генерации, а не отлавливаемыми постфактум.
THEME_PATTERN = "^[a-z0-9][a-z0-9_-]{2,29}$"


def _enum(values: list[str]) -> dict:
    return {"type": "string", "enum": values}


RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "mood": {
            "type": "array",
            "items": _enum(MOODS),
            "minItems": 1,
            "maxItems": 3,
            "uniqueItems": True,
        },
        "themes": {
            "type": "array",
            "items": {"type": "string", "pattern": THEME_PATTERN},
            "minItems": 2,
            "maxItems": 5,
        },
        "emotional_arc": _enum(EMOTIONAL_ARCS),
        "pov": _enum(POVS),
        "register": _enum(REGISTERS),
        "concreteness": _enum(CONCRETENESS),
        "stance": _enum(STANCES),
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "summary": {"type": "string"},
        "resonance": {"type": "string"},
        "key_line": {"type": "string"},
    },
    "required": [
        "mood",
        "themes",
        "emotional_arc",
        "pov",
        "register",
        "concreteness",
        "stance",
        "confidence",
        "summary",
        "resonance",
        "key_line",
    ],
    "additionalProperties": False,
}


def lyrics_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def verify_key_line(key_line: str, lyrics: str) -> bool:
    """Цитата ли key_line на самом деле - модель иногда пересказывает вместо цитирования."""
    if not key_line.strip():
        return False
    return _normalized(key_line) in _normalized(lyrics)


def is_fresh(entry: dict | None, model: str, prompt_version: int, text_hash: str) -> bool:
    if not entry or "error" in entry:
        return False
    return (
        entry.get("model") == model
        and entry.get("prompt_version") == prompt_version
        and entry.get("lyrics_hash") == text_hash
    )


def top_themes(cache: dict[str, dict], limit: int = 60) -> list[str]:
    """Самые частые уже присвоенные темы - подмешиваются в промпт, чтобы словарь тем
    сходился по всей библиотеке, а не расползался в синонимы."""
    counter: Counter[str] = Counter()
    for entry in cache.values():
        counter.update(entry.get("themes", []))
    return [theme for theme, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def load_analysis(cache_dir: Path) -> dict[str, dict]:
    cache_file = cache_dir / ANALYSIS_CACHE_FILE
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return {}


@dataclass(frozen=True)
class OllamaSettings:
    host: str
    model: str
    prompt_version: int
    timeout: float
    keep_alive: str


PROMPT_TEMPLATE = """Ты разбираешь текст песни для профиля музыкального вкуса одного слушателя.

Трек: «{title}» — {artists}

Текст:
\"\"\"
{lyrics}
\"\"\"
{themes_hint}
Заполни поля схемы. Требования:
- summary: 2-4 предложения по-русски о том, что в песне происходит и как это подано.
- resonance: 1-2 предложения по-русски о том, чем этот текст может цеплять слушателя.
- key_line: одна строка ДОСЛОВНО из текста выше, без изменений и без пересказа.
- themes: 2-5 тем на английском в snake_case (1-3 слова, единственное число).
- Остальные поля выбирай строго из допустимых значений схемы.
"""

THEMES_HINT_TEMPLATE = """
Уже использованные темы в этой библиотеке (переиспользуй подходящую, иначе придумай новую):
{themes}
"""


def build_prompt(title: str, artists: list[str], lyrics: str, known_themes: list[str]) -> str:
    themes_hint = THEMES_HINT_TEMPLATE.format(themes=", ".join(known_themes)) if known_themes else ""
    return PROMPT_TEMPLATE.format(
        title=title,
        artists=", ".join(artists),
        lyrics=lyrics,
        themes_hint=themes_hint,
    )


def call_ollama(settings: OllamaSettings, prompt: str) -> dict:
    """think=True уводит рассуждение в отдельное поле message.thinking, а format (полная
    JSON Schema, не строка "json") констрейнит только финальный ответ - модель думает
    свободно, результат при этом гарантированно парсится. num_predict=-1: капать вывод
    нельзя, обрыв на середине даст невалидный JSON вместо просто короткого ответа."""
    payload = {
        "model": settings.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": True,
        "format": RESPONSE_SCHEMA,
        "keep_alive": settings.keep_alive,
        "options": {"num_predict": -1, "temperature": 0.65},
    }
    request = urllib.request.Request(
        f"{settings.host.rstrip('/')}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["message"]["content"])
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP Error {e.code}: {e.reason}\n{error_body}") from e


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _track_meta(tracks_cache: dict[str, dict]) -> dict[str, dict]:
    """Числовой id -> название и исполнители. Ключ tracks_cache составной ("id:album_id"),
    а кэши текста и разбора живут на числовом id, как и cache/lyrics_lang.json."""
    return {str(t["id"]): {"title": t["title"], "artists": t["artists"]} for t in tracks_cache.values()}


def analyze_tracks(
    tracks_cache: dict[str, dict],
    lyrics_cache: dict[str, str | None],
    cache_dir: Path,
    settings: OllamaSettings,
    limit: int | None = None,
    call: Callable[[OllamaSettings, str], dict] = call_ollama,
) -> dict[str, dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / ANALYSIS_CACHE_FILE
    cache = load_analysis(cache_dir)
    meta = _track_meta(tracks_cache)

    pending = []
    for tid, text in lyrics_cache.items():
        if not text:
            continue
        text_hash = lyrics_hash(text)
        if is_fresh(cache.get(tid), settings.model, settings.prompt_version, text_hash):
            continue
        pending.append((tid, text, text_hash))

    if limit is not None:
        pending = pending[:limit]

    if not pending:
        print("Все тексты уже разобраны.")
        return cache

    print(f"Разбор текстов: {len(pending)} треков, модель {settings.model}")
    failed = 0
    for i, (tid, text, text_hash) in enumerate(pending, 1):
        info = meta.get(tid, {"title": tid, "artists": []})
        prompt = build_prompt(info["title"], info["artists"], text, top_themes(cache))
        stamp = {
            "model": settings.model,
            "prompt_version": settings.prompt_version,
            "lyrics_hash": text_hash,
            "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            data = call(settings, prompt)
            entry = {**data, **stamp, "key_line_verified": verify_key_line(data["key_line"], text)}
        # Широкий except намеренно: трёхчасовой прогон не должен падать целиком из-за
        # одного зависшего/битого ответа локальной модели - в том числе синтаксически
        # валидного JSON без обязательного поля (KeyError здесь же, не только в call()).
        # KeyboardInterrupt и SystemExit наследуются от BaseException и сюда не попадают -
        # Ctrl+C прерывает прогон.
        except Exception as e:
            cache[tid] = {**stamp, "error": f"{type(e).__name__}: {e}"}
            failed += 1
            print(f"  [{i}/{len(pending)}] {info['title']} - ошибка: {type(e).__name__}")
        else:
            cache[tid] = entry
            print(f"  [{i}/{len(pending)}] {info['title']} - {', '.join(entry.get('mood', []))}")
        _atomic_write_json(cache_file, cache)

    if failed:
        print(f"  не разобрано: {failed} - повторный запуск analyze попробует их снова")
    return cache

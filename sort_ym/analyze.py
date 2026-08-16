from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

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
THEME_PATTERN = "^[a-z][a-z0-9_]{2,29}$"


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

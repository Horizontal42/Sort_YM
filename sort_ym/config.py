from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path.cwd()


@dataclass(frozen=True)
class Config:
    fetch_batch_delay: float
    lyrics_request_delay: float
    apply_request_delay: float
    request_timeout: float
    batch_size: int
    small_group_min: int
    digest_top_artists: int
    digest_top_albums: int
    ollama_host: str
    ollama_model: str
    ollama_prompt_version: int
    ollama_timeout: float
    ollama_keep_alive: str
    token_file: Path
    cache_dir: Path
    out_dir: Path


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.toml"
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)

        return Config(
            fetch_batch_delay=data["throttle"]["fetch_batch_delay"],
            lyrics_request_delay=data["throttle"]["lyrics_request_delay"],
            apply_request_delay=data["throttle"]["apply_request_delay"],
            request_timeout=data["throttle"]["request_timeout"],
            batch_size=data["fetch"]["batch_size"],
            small_group_min=data["classify"]["small_group_min"],
            digest_top_artists=data["digest"]["top_artists"],
            digest_top_albums=data["digest"]["top_albums"],
            ollama_host=data["ollama"]["host"],
            ollama_model=data["ollama"]["model"],
            ollama_prompt_version=data["ollama"]["prompt_version"],
            ollama_timeout=data["ollama"]["timeout"],
            ollama_keep_alive=data["ollama"]["keep_alive"],
            token_file=ROOT / data["paths"]["token_file"],
            cache_dir=ROOT / data["paths"]["cache_dir"],
            out_dir=ROOT / data["paths"]["out_dir"],
        )
    except (KeyError, tomllib.TOMLDecodeError) as e:
        raise SystemExit(f"Ошибка в конфигурационном файле {path}: {type(e).__name__}: {e}") from e

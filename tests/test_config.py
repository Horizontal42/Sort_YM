from pathlib import Path

from sort_ym.config import load_config

MINIMAL_TOML = """
[throttle]
fetch_batch_delay = 0.4
lyrics_request_delay = 0.25
apply_request_delay = 0.3
request_timeout = 20

[fetch]
batch_size = 100

[classify]
small_group_min = 12

[digest]
top_artists = 40
top_albums = 15

[ollama]
host = "http://localhost:11434"
model = "qwen3.6-35b-a3b:latest"
prompt_version = 1
timeout = 600
keep_alive = "30m"

[paths]
token_file = ".token"
cache_dir = "cache"
out_dir = "out"
"""


def test_load_config_reads_ollama_block(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL_TOML, encoding="utf-8")

    cfg = load_config(path)

    assert cfg.ollama_host == "http://localhost:11434"
    assert cfg.ollama_model == "qwen3.6-35b-a3b:latest"
    assert cfg.ollama_prompt_version == 1
    assert cfg.ollama_timeout == 600
    assert cfg.ollama_keep_alive == "30m"

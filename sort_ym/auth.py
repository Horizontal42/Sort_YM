from __future__ import annotations

from pathlib import Path

from yandex_music import Client, DeviceCode
from yandex_music.exceptions import DeviceAuthError


def load_token(token_file: Path) -> str | None:
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        return token or None
    return None


def save_token(token_file: Path, token: str) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    import os
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with open(os.open(token_file, flags, 0o600), "w", encoding="utf-8") as f:
        f.write(token)


def _on_code(code: DeviceCode) -> None:
    print(f"Откройте {code.verification_url} и введите код: {code.user_code}")
    print("Ожидание подтверждения...")


def device_login(token_file: Path) -> str:
    client = Client()
    try:
        oauth_token = client.device_auth(_on_code)
    except DeviceAuthError as e:
        raise SystemExit(f"Не удалось авторизоваться: {e}") from e

    save_token(token_file, oauth_token.access_token)
    print("Токен сохранён.")
    return oauth_token.access_token


def get_token(token_file: Path) -> str:
    token = load_token(token_file)
    if token:
        return token
    return device_login(token_file)

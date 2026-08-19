from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from typing import TypeVar

from yandex_music import Client
from yandex_music.exceptions import BadRequestError, NetworkError, NotFoundError

T = TypeVar("T")


def make_client(token: str, request_timeout: float = 20) -> Client:
    client = Client(token=token)
    client.request.set_timeout(request_timeout)
    with_retries(lambda: client.init())
    return client


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    if size <= 0:
        raise ValueError("size must be > 0")
    for i in range(0, len(items), size):
        yield items[i : i + size]


def with_retries(fn: Callable[[], T], max_attempts: int = 4, base_delay: float = 2.0) -> T:
    """Повторяет вызов при временных сетевых сбоях (таймауты и т.п.) с экспоненциальной паузой.

    NotFoundError и BadRequestError не повторяются - это окончательные ответы сервера
    (данные точно не найдены / запрос точно невалиден), а не сбои сети, хотя формально
    оба тоже унаследованы от NetworkError. Повтор такого запроса даст тот же результат.
    """
    if max_attempts <= 0:
        max_attempts = 1
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except (NotFoundError, BadRequestError):
            raise
        except Exception as e:
            if isinstance(e, (TypeError, ValueError, AttributeError, NameError)):
                raise
            last_exc = e
            if attempt < max_attempts - 1:
                wait = base_delay * (2**attempt)
                print(f"  сетевая ошибка ({type(e).__name__}: {e}), повтор через {wait:.0f}с...")
                time.sleep(wait)

    assert last_exc is not None
    raise last_exc

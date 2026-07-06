from __future__ import annotations

import time
from typing import Callable, Iterator, List, TypeVar

from yandex_music import Client
from yandex_music.exceptions import BadRequestError, NetworkError, NotFoundError

T = TypeVar("T")


def make_client(token: str, request_timeout: float = 20) -> Client:
    client = Client(token=token)
    client.request.set_timeout(request_timeout)
    with_retries(lambda: client.init())
    return client


def chunked(items: List[T], size: int) -> Iterator[List[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def with_retries(fn: Callable[[], T], max_attempts: int = 4, base_delay: float = 2.0) -> T:
    """Повторяет вызов при временных сетевых сбоях (таймауты и т.п.) с экспоненциальной паузой.

    NotFoundError и BadRequestError не повторяются - это окончательные ответы сервера
    (данные точно не найдены / запрос точно невалиден), а не сбои сети, хотя формально
    оба тоже унаследованы от NetworkError. Повтор такого запроса даст тот же результат.
    """
    last_exc: NetworkError | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except (NotFoundError, BadRequestError):
            raise
        except NetworkError as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = base_delay * (2**attempt)
                print(f"  сетевая ошибка ({e}), повтор через {wait:.0f}с...")
                time.sleep(wait)

    assert last_exc is not None
    raise last_exc

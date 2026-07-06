from __future__ import annotations

from typing import Iterator, List, TypeVar

from yandex_music import Client

T = TypeVar("T")


def make_client(token: str) -> Client:
    client = Client(token=token)
    client.init()
    return client


def chunked(items: List[T], size: int) -> Iterator[List[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]

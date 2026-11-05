"""Транспортные повторы SDK отделены от повторов валидации instructor."""

from collections.abc import Iterator
from contextlib import contextmanager

import instructor
from openai import OpenAI

from src.config import Settings


@contextmanager
def create_client(settings: Settings) -> Iterator[instructor.Instructor]:
    # SDK повторяет только временные сетевые ошибки (включая 429 и 5xx)
    # с экспоненциальным backoff и jitter. Собственного цикла валидации нет.
    with OpenAI(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.timeout,
        max_retries=2,
    ) as sdk:
        yield instructor.from_openai(sdk, mode=instructor.Mode.TOOLS)

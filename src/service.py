"""Один пайплайн для CLI и HTTP. Невалидный черновик не становится карточкой."""

import json
from typing import Any

from instructor.core.exceptions import IncompleteOutputException, InstructorRetryException
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import ValidationError

from src.config import ConfigurationError, Settings, load_settings
from src.llm_client import create_client
from src.prompts import build_messages
from src.schemas import ErrorResponse, ProductCard
from src.validators import InputError, find_missing_fields, input_warnings, parse_product


class ServiceError(Exception):
    def __init__(self, response: ErrorResponse, status_code: int = 422) -> None:
        super().__init__(response.error)
        self.response = response
        self.status_code = status_code


def _last_attempt(completion: Any) -> str | None:
    """Возвращает только содержимое ответа, без SDK-метаданных и истории промптов."""
    if completion is None:
        return None
    if isinstance(completion, str):
        return completion
    if isinstance(completion, dict):
        choices = completion.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        calls = message.get("tool_calls") or []
        return calls[0].get("function", {}).get("arguments") if calls else message.get("content")
    choices = getattr(completion, "choices", [])
    if not choices:
        return None
    message = choices[0].message
    if calls := getattr(message, "tool_calls", None):
        return calls[0].function.arguments
    return getattr(message, "content", None)


def _find_api_error(exc: BaseException) -> APIError | None:
    # Instructor оборачивает также исчерпанные транспортные ошибки SDK.
    pending = [exc]
    visited: set[int] = set()
    while pending:
        item = pending.pop()
        if id(item) in visited:
            continue
        visited.add(id(item))
        if isinstance(item, APIError):
            return item
        pending.extend(arg for arg in item.args if isinstance(arg, BaseException))
        pending.extend(cause for cause in (item.__cause__, item.__context__) if cause is not None)
        pending.extend(
            attempt.exception
            for attempt in getattr(item, "failed_attempts", []) or []
            if isinstance(attempt.exception, BaseException)
        )
    return None


def _api_failure(exc: APIError, missing: list[str]) -> ServiceError:
    if isinstance(exc, APITimeoutError):
        message, code, status = (
            "Превышено время ожидания OpenAI. Повторите запрос позже.",
            "timeout",
            504,
        )
    elif isinstance(exc, RateLimitError):
        message, code, status = (
            "OpenAI ограничил частоту запросов или исчерпана квота. Проверьте лимиты аккаунта.",
            "rate_limit",
            429,
        )
    elif isinstance(exc, AuthenticationError):
        message, code, status = (
            "OpenAI отклонил API-ключ. Проверьте OPENAI_API_KEY.",
            "auth_error",
            503,
        )
    elif isinstance(exc, APIConnectionError):
        message, code, status = (
            "Не удалось соединиться с OpenAI. Проверьте сеть.",
            "connection_error",
            503,
        )
    elif isinstance(exc, APIStatusError) and exc.status_code >= 500:
        message, code, status = (
            "OpenAI временно недоступен. Повторите запрос позже.",
            "provider_error",
            503,
        )
    else:
        message, code, status = (
            "OpenAI отклонил запрос. Проверьте доступ к OPENAI_MODEL и настройки аккаунта.",
            "api_error",
            502,
        )
    return ServiceError(ErrorResponse(error=message, code=code, missing_fields=missing), status)


def generate_card(raw: str | bytes, *, settings: Settings | None = None) -> ProductCard:
    try:
        product = parse_product(raw)
    except InputError as exc:
        raise ServiceError(ErrorResponse(error=str(exc), code="invalid_input")) from exc
    missing = find_missing_fields(product)
    warnings = input_warnings(product)
    try:
        settings = settings or load_settings()
    except ConfigurationError as exc:
        raise ServiceError(
            ErrorResponse(error=str(exc), code="configuration_error", missing_fields=missing),
            503,
        ) from exc

    validation_context = {"product": product, "missing_fields": missing}
    try:
        with create_client(settings) as client:
            card = client.chat.completions.create(
                model=settings.model,
                response_model=ProductCard,
                messages=build_messages(product, missing, warnings),
                # instructor 1.17 называет аргумент context и передаёт его
                # в Pydantic как validation_context (доступен через info.context).
                context=validation_context,
                max_retries=2,
                temperature=0.1,
            )
    except (InstructorRetryException, IncompleteOutputException) as exc:
        if provider_error := _find_api_error(exc):
            raise _api_failure(provider_error, missing) from exc
        raise ServiceError(
            ErrorResponse(
                error=(
                    "Ответ модели не прошёл проверку или был обрезан. "
                    "Уточните данные или повторите запрос."
                ),
                code="invalid_model_response",
                missing_fields=missing,
                warnings=[
                    *warnings,
                    "Последняя попытка не проверена и может содержать выдуманные данные.",
                ],
                last_attempt=_last_attempt(getattr(exc, "last_completion", None)),
            ),
            502,
        ) from exc
    except APIError as exc:
        raise _api_failure(exc, missing) from exc
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ServiceError(
            ErrorResponse(
                error="Модель вернула некорректный ответ. Повторите запрос.",
                code="invalid_model_response",
                missing_fields=missing,
                warnings=warnings,
            ),
            502,
        ) from exc

    # Детерминированные пропуски и предупреждения нельзя потерять из-за ответа LLM.
    updates = card.model_dump()
    updates["missing_fields"] = list(dict.fromkeys([*missing, *card.missing_fields]))
    updates["warnings"] = list(dict.fromkeys([*warnings, *card.warnings]))
    existing = {item.name for item in card.key_specs}
    for path in missing:
        if path.startswith("specs.") and path[6:] not in existing:
            updates["key_specs"].append({"name": path[6:], "value": "данных нет"})
    return ProductCard.model_validate(updates, context=validation_context)

import json

import httpx2 as httpx
import pytest
from instructor.core.exceptions import InstructorRetryException
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from src.service import ServiceError, generate_card
from tests.conftest import ROOT, completion


def test_success_with_real_instructor(raw_product, sdk_create):
    result = generate_card(raw_product)
    assert result.seo_title.startswith("Манометр")
    assert result.warnings  # Короткое исходное описание не потерялось.
    assert sdk_create.call_count == 1


def test_validation_retry_receives_error(raw_product, sdk_create, card_data):
    bad = {**card_data, "seo_title": "Т" * 71}
    sdk_create.side_effect = [completion(bad), completion(card_data)]
    result = generate_card(raw_product)
    assert result.seo_title == card_data["seo_title"]
    assert sdk_create.call_count == 2
    assert "70" in str(sdk_create.call_args.kwargs["messages"])


def test_exhausted_validation_returns_last_attempt(raw_product, sdk_create, card_data):
    sdk_create.return_value = completion({**card_data, "seo_title": "Т" * 71})
    with pytest.raises(ServiceError) as error:
        generate_card(raw_product)
    assert error.value.response.code == "invalid_model_response"
    assert error.value.response.last_attempt is not None
    assert json.loads(error.value.response.last_attempt)["seo_title"] == "Т" * 71
    assert any("не проверена" in text for text in error.value.response.warnings)
    assert sdk_create.call_count == 3  # Запрос и два валидационных повтора.


def test_missing_fields_survive_model_omission(sdk_create, card_data):
    raw = (ROOT / "examples/product_2.json").read_text(encoding="utf-8")
    card_data.update(
        seo_title="Термопреобразователь сопротивления",
        seo_description="Данных о диапазоне и точности нет. " * 25,
        key_specs=[{"name": "назначение", "value": "измерение температуры"}],
        search_queries=[
            "термопреобразователь",
            "датчик температуры",
            "прибор измерения температуры",
        ],
    )
    sdk_create.return_value = completion(card_data)
    result = generate_card(raw)
    assert "manufacturer" in result.missing_fields
    assert {item.name: item.value for item in result.key_specs}[
        "Диапазон измерений"
    ] == "данных нет"


def test_missing_key_is_actionable(raw_product):
    with pytest.raises(ServiceError, match="OPENAI_API_KEY") as error:
        generate_card(raw_product)
    assert error.value.response.code == "configuration_error"


def api_exception(kind):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    if kind == "timeout":
        return APITimeoutError(request=request)
    if kind == "connection_error":
        return APIConnectionError(request=request)
    classes = {
        "rate_limit": (RateLimitError, 429),
        "provider_error": (InternalServerError, 503),
        "auth_error": (AuthenticationError, 401),
        "api_error": (BadRequestError, 400),
    }
    cls, status = classes[kind]
    return cls(
        "sensitive provider details", response=httpx.Response(status, request=request), body={}
    )


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "connection_error",
        "rate_limit",
        "provider_error",
        "auth_error",
        "api_error",
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_api_errors_have_safe_messages(kind, wrapped, raw_product, sdk_create):
    error = api_exception(kind)
    if wrapped:
        error = InstructorRetryException(error, n_attempts=1, total_usage=None)
    sdk_create.side_effect = error
    with pytest.raises(ServiceError) as caught:
        generate_card(raw_product)
    assert caught.value.response.code == kind
    assert "sensitive" not in caught.value.response.model_dump_json()


def test_retry_without_completion_is_safe(raw_product, sdk_create):
    sdk_create.side_effect = InstructorRetryException(
        ValueError("invalid"), n_attempts=3, total_usage=None
    )
    with pytest.raises(ServiceError) as error:
        generate_card(raw_product)
    assert error.value.response.last_attempt is None


@pytest.mark.parametrize("mode", ["truncated", "invalid_json", "empty_choices", "refusal"])
def test_malformed_model_responses_are_safe(mode, raw_product, sdk_create, card_data):
    response = completion(card_data)
    if mode == "truncated":
        response.choices[0].finish_reason = "length"
    elif mode == "invalid_json":
        response.choices[0].message.tool_calls[0].function.arguments = "{"
    elif mode == "empty_choices":
        response.choices = []
    else:
        response.choices[0].message.refusal = "Cannot answer"
        response.choices[0].message.tool_calls = None
        response.choices[0].finish_reason = "stop"
    sdk_create.return_value = response
    with pytest.raises(ServiceError) as error:
        generate_card(raw_product)
    assert error.value.response.code == "invalid_model_response"

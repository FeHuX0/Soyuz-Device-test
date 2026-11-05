"""Реальные instructor и SDK, но HTTP целиком перехвачен MockTransport."""

import httpx2 as httpx
import pytest
from openai import OpenAI

from src.service import ServiceError, generate_card
from tests.conftest import completion


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, "rate_limit"),
        (503, "provider_error"),
        (None, "timeout"),
        (401, "auth_error"),
    ],
)
def test_transport_backoff_does_not_restart_validation(
    status,
    code,
    settings,
    raw_product,
    mocker,
):
    requests = []

    def handler(request):
        requests.append(request)
        if status is None:
            raise httpx.ReadTimeout("private transport details", request=request)
        return httpx.Response(status, json={"error": {"message": "provider unavailable"}})

    sdk = OpenAI(
        api_key=settings.api_key.get_secret_value(),
        timeout=settings.timeout,
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    mocker.patch("src.llm_client.OpenAI", return_value=sdk)
    sleep = mocker.patch("openai._base_client.time.sleep")
    with pytest.raises(ServiceError) as error:
        generate_card(raw_product, settings=settings)
    assert error.value.response.code == code
    if status == 401:
        assert len(requests) == 1
        sleep.assert_not_called()
    else:
        # Ровно три HTTP-запроса от SDK. Instructor не запускает их заново.
        assert len(requests) == 3
        assert sleep.call_count == 2
        first, second = [call.args[0] for call in sleep.call_args_list]
        assert 0 < first < second  # Backoff увеличивается; реального ожидания нет.


def test_rate_limit_then_success(settings, raw_product, card_data, mocker):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"error": {"message": "try later"}})
        return httpx.Response(200, json=completion(card_data).model_dump(mode="json"))

    sdk = OpenAI(
        api_key=settings.api_key.get_secret_value(),
        timeout=settings.timeout,
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    mocker.patch("src.llm_client.OpenAI", return_value=sdk)
    mocker.patch("openai._base_client.time.sleep")
    result = generate_card(raw_product, settings=settings)
    assert result.seo_title == card_data["seo_title"]
    assert len(requests) == 2

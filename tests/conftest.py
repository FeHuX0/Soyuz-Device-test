"""Все ответы ниже — тестовые фикстуры, а не результаты настоящего LLM."""

import json
from pathlib import Path

import pytest
from openai.types.chat import ChatCompletion

from src.config import Settings
from src.schemas import ProductCard
from src.validators import find_missing_fields, parse_product

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, mocker):
    # Тесты не читают настоящий .env и не используют ключ разработчика.
    mocker.patch("src.config.load_dotenv")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings():
    return Settings(api_key="test-not-a-real-key", model="gpt-4.1-mini", timeout=1)


@pytest.fixture
def raw_product():
    return (ROOT / "examples/product_1.json").read_text(encoding="utf-8")


@pytest.fixture
def product(raw_product):
    return parse_product(raw_product)


@pytest.fixture
def card_data(product):
    description = (
        "Манометр показывающий DM 02 производства Манотомь предназначен для измерения "
        "избыточного давления. Диапазон измерений: 0–1,6 МПа. Класс точности: 1,5. "
        "Присоединение: G1/2. Диаметр корпуса: 100 мм. Указанные сведения позволяют "
        "контент-менеджеру подготовить основу карточки и передать параметры специалисту "
        "для проверки подбора. При выборе следует сопоставить исходные характеристики "
        "с требованиями конкретной задачи. Сведения о рабочих средах и условиях эксплуатации "
        "в источнике не приведены: данных нет. До подтверждения этих сведений нельзя "
        "делать вывод о совместимости прибора с оборудованием заказчика. Комплектность "
        "и условия поставки также требуют уточнения. Для согласования применения менеджеру "
        "следует запросить техническую документацию и уточнить условия установки. "
        "Описание составлено по переданным данным и предназначено для редакторской проверки. "
        "Исходный текст краткий, поэтому дополнительные свойства здесь не заявлены."
    )
    return {
        "seo_title": "Манометр показывающий DM 02 — Манотомь",
        "seo_description": description,
        "key_specs": [{"name": key, "value": value} for key, value in product.specs.items()],
        "search_queries": ["манометр DM 02", "манометр Манотомь", "манометр избыточного давления"],
        "manager_block": (
            "Для специалистов по измерению избыточного давления. Применимость уточняется."
        ),
        "missing_fields": [],
        "warnings": [],
    }


@pytest.fixture
def card(card_data, product):
    return ProductCard.model_validate(card_data, context={"product": product, "missing_fields": []})


def completion(data):
    return ChatCompletion.model_validate(
        {
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "test-call",
                                "type": "function",
                                "function": {
                                    "name": "ProductCard",
                                    "arguments": json.dumps(data, ensure_ascii=False),
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
    )


@pytest.fixture
def sdk_create(mocker, settings, card_data):
    mocker.patch("src.service.load_settings", return_value=settings)
    # Подменяем только сетевую границу SDK. Настоящие instructor, Pydantic и
    # контекстная валидация продолжают работать, включая коррекционные запросы.
    return mocker.patch(
        "openai.resources.chat.completions.Completions.create",
        return_value=completion(card_data),
    )


@pytest.fixture
def context(product):
    return {"product": product, "missing_fields": find_missing_fields(product)}

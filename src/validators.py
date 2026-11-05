"""Проверка входа и консервативная проверка фактов без второго LLM-запроса."""

import json
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.schemas import ProductInput

if TYPE_CHECKING:
    from src.schemas import ProductCard

NO_DATA = "данных нет"

# Это минимальный список вопросов для подбора КИП, а не каталог обязательных ТТХ.
SPEC_CHECKLIST = {
    "Диапазон измерений": ("диапазон", "предел измер"),
    "Точность / погрешность": ("точност", "погрешност"),
}
NUMBER = re.compile(r"(?<![\d.])[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?")
NUMERIC_PART = r"[+-]?\d+(?:\.\d+)?(?:\s*[-…]\s*[+-]?\d+(?:\.\d+)?)?"
# Любые буквенные единицы, включая неизвестные. Чтобы слово после номера
# модели не считалось единицей, известные идентификаторы удаляем отдельно.
UNIT = r"(?:°(?:\s*[^\W\d_]+)?|[%‰]|[^\W\d_]+)(?:\^?[23])?"
QUANTITY = re.compile(
    rf"(?<![\w.]){NUMERIC_PART}\s*{UNIT}(?:/[^\W\d_]+[23]?)?",
)
MODEL_ID = re.compile(r"(?<!\w)[A-ZА-ЯЁ]+[ -]*\d[\w./-]*")


class InputError(Exception):
    """Ошибка пользовательского JSON до обращения к API."""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-", ",": "."}))
    text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", normalize(text))


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Недопустимое значение JSON: {value}.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Повторяющийся ключ JSON: {key}.")
        result[key] = value
    return result


def parse_product(raw: str | bytes) -> ProductInput:
    try:
        data = json.loads(raw, parse_constant=_reject_nonfinite, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InputError(
            "Некорректный JSON. Проверьте кавычки, запятые и уникальность ключей."
        ) from exc
    try:
        product = ProductInput.model_validate(data)
    except ValidationError as exc:
        locations = ", ".join(".".join(map(str, item["loc"])) or "корень" for item in exc.errors())
        raise InputError(
            f"Неверная структура или типы полей: {locations}. "
            "Ожидается объект; name, manufacturer, description и значения specs — строки, "
            "specs — объект. null и неизвестные поля не поддерживаются."
        ) from exc
    if any(not key for key in product.specs):
        raise InputError("Название характеристики в specs не должно быть пустым.")
    if not any((product.name, product.manufacturer, product.description, *product.specs.values())):
        raise InputError("Нет полезных данных о приборе. Заполните название, описание или specs.")
    return product


def find_missing_fields(product: ProductInput) -> list[str]:
    missing = [
        field for field in ("name", "manufacturer", "description") if not getattr(product, field)
    ]
    if not product.specs or not any(product.specs.values()):
        missing.append("specs")
    missing.extend(f"specs.{key}" for key, value in product.specs.items() if not value)
    filled_keys = " ".join(normalize(key) for key, value in product.specs.items() if value)
    for label, aliases in SPEC_CHECKLIST.items():
        if not any(alias in filled_keys for alias in aliases):
            path = f"specs.{label}"
            if not any(normalize(item) == normalize(path) for item in missing):
                missing.append(path)
    return missing


def input_warnings(product: ProductInput) -> list[str]:
    warnings = []
    if len(product.description) < 80:
        warnings.append(
            "Исходное описание короткое; назначение и условия применения требуют проверки."
        )
    if not any(product.specs.values()):
        warnings.append(
            "Характеристики не заполнены; подбор прибора по техническим параметрам невозможен."
        )
    return warnings


def check_card_grounding(
    card: "ProductCard",
    product: ProductInput,
    missing_fields: list[str],
) -> None:
    sources = [
        normalize(value)
        for value in (
            product.name,
            product.manufacturer,
            product.description,
            *(f"{key}: {value}" for key, value in product.specs.items()),
        )
    ]
    numbers = {number for text in sources for number in NUMBER.findall(text)}
    identifiers = [normalize(match[0]) for match in MODEL_ID.finditer(product.name)]

    def quantities(text: str) -> set[str]:
        for identifier in identifiers:
            pattern = re.escape(identifier).replace(r"\ ", r"\s*")
            text = re.sub(rf"(?<!\w){pattern}(?!\w)", " ", text)
        return {compact(match[0]) for match in QUANTITY.finditer(text)}

    source_quantities = {quantity for text in sources for quantity in quantities(text)}
    # Сопоставление целых пар сильнее поиска отдельных чисел: нельзя заменить
    # диаметр числом из диапазона или приписать новую ненумерическую характеристику.
    expected = {key: value for key, value in product.specs.items() if value}
    allowed_missing = {item[6:] for item in missing_fields if item.startswith("specs.")}
    seen: set[str] = set()
    for spec in card.key_specs:
        if spec.name in seen:
            raise ValueError(f"key_specs: повтор характеристики «{spec.name}».")
        seen.add(spec.name)
        if spec.value == NO_DATA and spec.name in allowed_missing:
            continue
        if expected.get(spec.name) != spec.value:
            raise ValueError(
                f"key_specs: пара «{spec.name}: {spec.value}» отсутствует во входном specs. "
                "Скопируй исходные название и значение без изменений."
            )
    if omitted := expected.keys() - seen:
        raise ValueError(
            f"key_specs: пропущены исходные характеристики: {', '.join(sorted(omitted))}."
        )

    texts = [
        ("seo_title", card.seo_title),
        ("seo_description", card.seo_description),
        ("manager_block", card.manager_block),
        *(("search_queries", query) for query in card.search_queries),
    ]
    for field, text in texts:
        normalized = normalize(text)
        for number in NUMBER.findall(normalized):
            if number not in numbers:
                raise ValueError(f"{field}: число «{number}» отсутствует во входных данных.")
        for quantity in quantities(normalized):
            if quantity not in source_quantities:
                raise ValueError(
                    f"{field}: значение с единицей «{quantity}» отсутствует во входных данных. "
                    "Не меняй единицы, диапазоны и числовые значения."
                )
    if any(not query.strip() for query in card.search_queries):
        raise ValueError("search_queries: поисковые запросы не должны быть пустыми.")
    if len({query.strip().casefold() for query in card.search_queries}) != len(card.search_queries):
        raise ValueError("search_queries: запросы должны различаться.")

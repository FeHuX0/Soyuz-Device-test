import pytest
from pydantic import ValidationError

from src.render import to_markdown
from src.schemas import ProductCard
from src.validators import find_missing_fields, parse_product
from tests.conftest import ROOT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seo_title", "Т" * 71),
        ("seo_title", ""),
        ("seo_description", "а" * 799),
        ("seo_description", "а" * 1201),
        ("search_queries", ["один", "два"]),
        ("search_queries", ["а", "б", "в", "г", "д", "е"]),
        ("search_queries", ["манометр", "манометр", "манометр давления"]),
        ("search_queries", ["манометр", "  ", "манометр давления"]),
    ],
)
def test_schema_constraints(field, value, card_data, context):
    card_data[field] = value
    with pytest.raises(ValidationError):
        ProductCard.model_validate(card_data, context=context)


@pytest.mark.parametrize("length", [800, 1200])
def test_description_exact_boundaries(length, card_data, context):
    card_data["seo_description"] = "а" * length
    card_data["seo_title"] = "Т" * 70
    assert len(ProductCard.model_validate(card_data, context=context).seo_description) == length


def test_context_is_required(card_data):
    with pytest.raises(ValidationError, match="validation_context"):
        ProductCard.model_validate(card_data)


@pytest.mark.parametrize(
    "claim",
    [
        " Диаметр 150 мм.",
        " Давление 100 бар.",
        " Питание 02 В.",
        " Давление -100 МПа.",
        " Давление 1,5 psi.",
        " Диаметр 100 фут.",
        " Давление 100 абв.",
        " Сертификат ГОСТ 9999.",
    ],
)
def test_invented_numbers_or_unit_combinations(claim, card_data, context):
    card_data["seo_description"] += claim
    with pytest.raises(ValidationError, match="отсутствует во входных данных"):
        ProductCard.model_validate(card_data, context=context)


@pytest.mark.parametrize(
    "change",
    [
        {"name": "материал", "value": "сталь"},
        {"name": "диаметр корпуса", "value": "1,5"},
        {"name": "диаметр корпуса", "value": "100 бар"},
    ],
)
def test_ungrounded_spec_pairs(change, card_data, context):
    card_data["key_specs"][0] = change
    with pytest.raises(ValidationError, match="key_specs"):
        ProductCard.model_validate(card_data, context=context)


def test_cannot_silently_omit_or_duplicate_spec(card_data, context):
    original = card_data["key_specs"].pop()
    with pytest.raises(ValidationError, match="пропущены"):
        ProductCard.model_validate(card_data, context=context)
    card_data["key_specs"].extend([original, original])
    with pytest.raises(ValidationError, match="повтор"):
        ProductCard.model_validate(card_data, context=context)


def test_decimal_separator_and_unit_spaces_normalized(card_data, context):
    card_data["seo_description"] = card_data["seo_description"].replace("0–1,6 МПа", "0-1.6МПа")
    ProductCard.model_validate(card_data, context=context)


@pytest.mark.parametrize("name", ["product_1", "product_2"])
def test_saved_example_outputs_are_valid_and_grounded(name):
    raw_in = (ROOT / f"examples/{name}.json").read_text(encoding="utf-8")
    raw_out = (ROOT / f"examples/output/{name}.json").read_text(encoding="utf-8")
    md_out = (ROOT / f"examples/output/{name}.md").read_text(encoding="utf-8")
    product = parse_product(raw_in)
    missing = find_missing_fields(product)
    card = ProductCard.model_validate_json(
        raw_out,
        context={"product": product, "missing_fields": missing},
    )
    assert to_markdown(card) == md_out

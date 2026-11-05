import json

import pytest

from src.service import ServiceError, generate_card
from src.validators import InputError, find_missing_fields, parse_product
from tests.conftest import ROOT


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "[]",
        "null",
        "{}",
        '{"name": null}',
        '{"name": 42}',
        '{"name":"Прибор", "specs":[]}',
        '{"specs":{"давление": 5}}',
        '{"name":"Прибор", "specs":{"": "значение"}}',
        '{"name":"Прибор", "name":"Другой"}',
        '{"name":NaN}',
        '{"name":"Прибор", "extra":"неизвестное поле"}',
        '{"name":"  ", "specs":{"диапазон":"  "}}',
    ],
)
def test_invalid_input_never_reaches_llm(raw, mocker):
    client = mocker.patch("src.service.create_client")
    settings = mocker.patch("src.service.load_settings")
    with pytest.raises(ServiceError) as error:
        generate_card(raw)
    assert error.value.response.code == "invalid_input"
    client.assert_not_called()
    settings.assert_not_called()


def test_broken_json_example():
    with pytest.raises(InputError, match="JSON"):
        parse_product((ROOT / "examples/invalid_json.json").read_text(encoding="utf-8"))


def test_missing_fields_for_partial_product():
    product = parse_product((ROOT / "examples/product_2.json").read_text(encoding="utf-8"))
    assert find_missing_fields(product) == [
        "manufacturer",
        "specs.Диапазон измерений",
        "specs.Точность / погрешность",
    ]


def test_full_product_has_no_missing_fields(product):
    assert find_missing_fields(product) == []


def test_whitespace_empty_specs_and_omitted_fields():
    product = parse_product(json.dumps({"name": "  Датчик  ", "specs": {"диапазон": "  "}}))
    assert product.name == "Датчик"
    missing = find_missing_fields(product)
    assert {"manufacturer", "description", "specs", "specs.диапазон"} <= set(missing)


def test_empty_specs_example_is_useful_but_incomplete():
    product = parse_product((ROOT / "examples/empty_specs.json").read_text(encoding="utf-8"))
    assert "specs" in find_missing_fields(product)

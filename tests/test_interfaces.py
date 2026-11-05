import json

from fastapi.testclient import TestClient

from src.api import app
from src.cli import main
from src.render import to_markdown
from tests.conftest import ROOT


def test_cli_on_full_example(sdk_create, capsys):
    assert main([str(ROOT / "examples/product_1.json")]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["key_specs"]
    assert not captured.err


def test_cli_markdown_output(sdk_create, tmp_path, capsys):
    target = tmp_path / "card.md"
    assert (
        main(
            [
                str(ROOT / "examples/product_1.json"),
                "--format",
                "markdown",
                "--output",
                str(target),
            ]
        )
        == 0
    )
    assert "## Ключевые характеристики" in target.read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""


def test_cli_invalid_json_does_not_write_output(sdk_create, tmp_path, capsys):
    target = tmp_path / "card.json"
    assert main([str(ROOT / "examples/invalid_json.json"), "--output", str(target)]) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "invalid_input"
    assert not target.exists()
    sdk_create.assert_not_called()


def test_cli_missing_file(capsys):
    assert main([str(ROOT / "examples/does-not-exist.json")]) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "file_error"


def test_cli_without_key(capsys):
    assert main([str(ROOT / "examples/product_2.json")]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "configuration_error"
    assert "manufacturer" in error["missing_fields"]


def test_web_form_available_without_key():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert '<html lang="ru">' in response.text
    assert "Копировать Markdown" in response.text
    assert "Копировать JSON" in response.text


def test_api_json_and_both_formats_use_one_call(raw_product, sdk_create):
    with TestClient(app) as client:
        response = client.post("/api/generate", content=raw_product)
        assert response.status_code == 200
        assert "seo_title" in response.json()
        response = client.post("/api/generate?format=both", content=raw_product)
    data = response.json()
    assert response.status_code == 200
    assert data["card"]["seo_title"] in data["markdown"]
    assert sdk_create.call_count == 2


def test_api_markdown(raw_product, sdk_create):
    with TestClient(app) as client:
        response = client.post("/api/generate?format=markdown", content=raw_product)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# ")


def test_api_invalid_json_and_missing_key():
    with TestClient(app) as client:
        invalid = client.post("/api/generate", content="{")
        missing = client.post("/api/generate", json={"name": "Манометр"})
    assert invalid.status_code == 422
    assert missing.status_code == 503
    assert "OPENAI_API_KEY" in missing.json()["error"]
    assert "Traceback" not in invalid.text + missing.text


def test_unexpected_error_does_not_expose_traceback(mocker):
    mocker.patch("src.api.generate_card", side_effect=RuntimeError("SECRET"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/generate", json={"name": "Манометр"})
    assert response.status_code == 500
    assert "SECRET" not in response.text


def test_markdown_escapes_untrusted_text(card):
    # Проверяем только рендеринг: конструируем отдельную фикстуру с HTML и разделителем таблицы.
    card = card.model_copy(update={"manager_block": "<script>alert('x')</script> | *текст*"})
    result = to_markdown(card)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert r"\|" in result

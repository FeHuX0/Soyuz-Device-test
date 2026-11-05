"""Один Markdown-рендерер для CLI и кнопки копирования в браузере."""

import re

from src.schemas import ProductCard


def _escape(value: str) -> str:
    value = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)


def to_markdown(card: ProductCard) -> str:
    lines = [
        f"# {_escape(card.seo_title)}",
        "",
        "## SEO-описание",
        "",
        _escape(card.seo_description),
        "",
        "## Ключевые характеристики",
        "",
        "| Название | Значение |",
        "| --- | --- |",
        *(f"| {_escape(item.name)} | {_escape(item.value)} |" for item in card.key_specs),
        "",
        "## Поисковые запросы",
        "",
        *(f"- {_escape(query)}" for query in card.search_queries),
        "",
        "## Для менеджера",
        "",
        _escape(card.manager_block),
    ]
    for title, values in (
        ("Недостающие данные", card.missing_fields),
        ("Предупреждения", card.warnings),
    ):
        lines.extend(["", f"## {title}", ""])
        if values:
            lines.extend(f"- {_escape(value)}" for value in values)
        else:
            lines.append("Нет.")
    return "\n".join(lines) + "\n"

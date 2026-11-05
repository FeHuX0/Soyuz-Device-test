"""Общая схема ответа используется instructor, CLI и веб-интерфейсом."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator


class ProductInput(BaseModel):
    # Отсутствующие и пустые поля допустимы: они попадут в missing_fields.
    # strict=True исключает тихое преобразование чисел и null в строки.
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    name: str = ""
    manufacturer: str = ""
    specs: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class SpecItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, description="Название характеристики из входного specs.")
    value: str = Field(
        min_length=1,
        description="Точное исходное значение; для отсутствующей характеристики — «данных нет».",
    )


class ProductCard(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    seo_title: str = Field(
        min_length=1,
        max_length=70,
        description="SEO-заголовок на русском: прибор, модель и производитель, до 70 символов.",
    )
    seo_description: str = Field(
        min_length=800,
        max_length=1200,
        description=(
            "Русское B2B-описание от 800 до 1200 символов. Только факты из товара; "
            "числа и единицы копируй без изменения. Не придумывай свойства ради длины. "
            "Если информации мало, поясни ограничения выбора и перечисли, чего не хватает."
        ),
    )
    key_specs: list[SpecItem] = Field(
        description=(
            "Все непустые пары исходного specs без переименований и изменений значений. "
            "Для пропусков из missing_fields можно добавить значение «данных нет»."
        ),
    )
    search_queries: list[str] = Field(
        min_length=3,
        max_length=5,
        description="От трёх до пяти непустых русских поисковых запросов без переспама.",
    )
    manager_block: str = Field(
        min_length=1,
        description=(
            "Кратко по-русски: кому подходит прибор и какую задачу решает по исходному "
            "назначению. Неподтверждённую совместимость и отрасли не утверждай."
        ),
    )
    missing_fields: list[str] = Field(
        description=(
            "Сохрани весь список пропусков, рассчитанный кодом. Можно добавить конкретные "
            "вопросы для уточнения. Не называй заполненные данные отсутствующими."
        ),
    )
    warnings: list[str] = Field(
        description=(
            "Сомнения, противоречия и неоднозначности входа по-русски. "
            "Если сомнений нет, пустой список. Не скрывай противоречия догадкой."
        ),
    )

    @model_validator(mode="after")
    def grounded_in_source(self, info: ValidationInfo) -> Self:
        # Без исходного товара проверка не может считаться пройденной.
        # Локальный импорт разрывает зависимость схемы и функций проверки входа.
        from src.validators import check_card_grounding

        if not info.context or "product" not in info.context:
            raise ValueError(
                "Для проверки карточки необходим исходный product в validation_context."
            )
        check_card_grounding(self, info.context["product"], info.context.get("missing_fields", []))
        return self


class ErrorResponse(BaseModel):
    error: str
    code: str
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    last_attempt: str | None = None

"""Настройки читаются при запросе: импорт приложения не требует API-ключа."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(description="Ключ OpenAI из окружения")
    base_url: str | None = Field(default=None, min_length=1)
    model: str = Field(default="gpt-4.1-mini", min_length=1)
    timeout: float = Field(default=30, gt=0, le=300)


class ConfigurationError(Exception):
    """Ошибка окружения, которую можно безопасно показать пользователю."""


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ConfigurationError("Нет OPENAI_API_KEY. Укажите ключ в окружении или файле .env.")
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    try:
        return Settings(
            api_key=SecretStr(api_key),
            base_url=base_url,
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
            timeout=os.getenv("OPENAI_TIMEOUT", "30"),
        )
    except ValidationError as exc:
        raise ConfigurationError(
            "Проверьте OPENAI_MODEL и OPENAI_TIMEOUT: модель не должна быть пустой, "
            "таймаут должен быть числом больше нуля и не больше 300 секунд."
        ) from exc

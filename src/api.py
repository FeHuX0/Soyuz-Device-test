"""Локальная веб-форма и JSON API. Секреты и traceback в ответы не попадают."""

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from src.config import PROJECT_ROOT
from src.render import to_markdown
from src.schemas import ProductCard
from src.service import ServiceError, generate_card

app = FastAPI(title="AI-помощник КИП", debug=False)
logger = logging.getLogger(__name__)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.response.model_dump())


@app.exception_handler(RequestValidationError)
async def request_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "Проверьте параметр format: json, markdown или both.",
            "code": "invalid_request",
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Не логируем exception/body: ответы провайдера могут содержать входные данные.
    logger.error("Непредвиденная ошибка генерации: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Не удалось обработать запрос. Повторите попытку.",
            "code": "internal_error",
        },
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "templates" / "index.html", media_type="text/html")


@app.post("/api/generate", response_model=ProductCard)
async def generate(
    request: Request,
    format: Literal["json", "markdown", "both"] = "json",
) -> JSONResponse | PlainTextResponse:
    # Читаем исходный JSON сами, чтобы CLI и HTTP одинаково обрабатывали битый
    # JSON, отсутствующие поля, повторяющиеся ключи и строгие типы.
    card = await run_in_threadpool(generate_card, await request.body())
    if format == "markdown":
        return PlainTextResponse(to_markdown(card), media_type="text/markdown")
    if format == "both":
        return JSONResponse(content={"card": card.model_dump(), "markdown": to_markdown(card)})
    # JSONResponse избегает повторной Pydantic-валидации без исходного контекста.
    return JSONResponse(content=card.model_dump())

"""CLI: stdout содержит только выбранный формат, ошибки JSON уходят в stderr."""

import argparse
import sys
from pathlib import Path

from src.render import to_markdown
from src.schemas import ErrorResponse
from src.service import ServiceError, generate_card


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Черновик карточки прибора КИП через OpenAI")
    parser.add_argument("input", type=Path, help="Путь к входному JSON (UTF-8)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="Сохранить результат в файл UTF-8")
    args = parser.parse_args(argv)
    # Стабильная кириллица при перенаправлении stdout в Windows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raw = args.input.read_text(encoding="utf-8-sig")
        card = generate_card(raw)
        output = card.model_dump_json(indent=2) if args.format == "json" else to_markdown(card)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                output + ("" if output.endswith("\n") else "\n"), encoding="utf-8"
            )
        else:
            print(output)
    except ServiceError as exc:
        print(exc.response.model_dump_json(indent=2), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print(
            ErrorResponse(
                error=(
                    "Не удалось прочитать входной файл UTF-8 или сохранить результат. "
                    "Проверьте путь и права."
                ),
                code="file_error",
            ).model_dump_json(indent=2),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

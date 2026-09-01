"""Локальный запуск: python -m app (используется в `make run`)."""

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "local",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

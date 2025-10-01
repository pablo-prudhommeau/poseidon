from __future__ import annotations

from src.logging.logger import init_logging

init_logging()

import uvicorn

from src.configuration.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.API_HOST,
        port=settings.API_PORT
    )

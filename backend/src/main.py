from __future__ import annotations

import uvicorn

from src.configuration.config import settings
from src.logging.logger import init_logging

if __name__ == "__main__":
    init_logging()
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.API_HOST,
        port=settings.API_PORT
    )

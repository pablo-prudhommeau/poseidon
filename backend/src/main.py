import asyncio
import sys

from src.logging.logger import init_logging

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

init_logging()

import uvicorn

from src.configuration.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )

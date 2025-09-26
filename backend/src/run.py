# backend/src/run.py
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.api.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000"))
    )

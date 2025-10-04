from __future__ import annotations

import os
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Parse a truthy/falsey string into a boolean."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings:
    # API
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Core / modes
    PAPER_MODE: bool = _as_bool(os.getenv("PAPER_MODE"), True)
    PAPER_STARTING_CASH: float = float(os.getenv("PAPER_STARTING_CASH", "10000"))
    BASE_CURRENCY: str = os.getenv("BASE_CURRENCY", "EUR")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", str(Path(__file__).resolve().parents[2] / "data" / "poseidon.db"))

    # Infra / chain
    QUICKNODE_URL: str = os.getenv("QUICKNODE_URL", "")
    UNISWAP_FACTORY_ADDRESS: str = os.getenv(
        "UNISWAP_FACTORY_ADDRESS",
        "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    )
    WETH_ADDRESS: str = os.getenv(
        "WETH_ADDRESS",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    )

    # Debug / logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "WARNING").upper()
    LOG_LEVEL_POSEIDON: str = os.getenv("LOG_LEVEL_POSEIDON", "DEBUG").upper()
    LOG_LEVEL_LIB_REQUESTS: str = os.getenv("LOG_LEVEL_LIB_REQUESTS", "WARNING").upper()
    LOG_LEVEL_LIB_URLLIB3: str = os.getenv("LOG_LEVEL_LIB_URLLIB3", "WARNING".upper())
    LOG_LEVEL_LIB_WEBSOCKETS: str = os.getenv("LOG_LEVEL_LIB_WEBSOCKETS", "WARNING").upper()
    LOG_LEVEL_LIB_HTTPX: str = os.getenv("LOG_LEVEL_LIB_HTTPX", "WARNING").upper()
    LOG_LEVEL_LIB_HTTPCORE: str = os.getenv("LOG_LEVEL_LIB_HTTPCORE", "WARNING").upper()
    LOG_LEVEL_LIB_ASYNCIO: str = os.getenv("LOG_LEVEL_LIB_ASYNCIO", "WARNING").upper()
    LOG_LEVEL_LIB_ANYIO: str = os.getenv("LOG_LEVEL_LIB_ANYIO", "WARNING").upper()
    LOG_LEVEL_LIB_OPENAI: str = os.getenv("LOG_LEVEL_LIB_OPENAI", "WARNING").upper()

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Trending
    TREND_ENABLE: bool = _as_bool(os.getenv("TREND_ENABLE"), True)
    TREND_INTERVAL: str = os.getenv("TREND_INTERVAL", "1h").lower()
    TREND_PAGE_SIZE: int = int(os.getenv("TREND_PAGE_SIZE", "100"))
    TREND_MAX_RESULTS: int = int(os.getenv("TREND_MAX_RESULTS", "100"))
    TREND_MIN_PCT_5M: float = float(os.getenv("TREND_MIN_PCT_5M", "2"))
    TREND_MIN_PCT_1H: float = float(os.getenv("TREND_MIN_PCT_1H", "5"))
    TREND_MIN_PCT_24H: float = float(os.getenv("TREND_MIN_PCT_24H", "10"))
    TREND_MIN_VOL_USD: float = float(os.getenv("TREND_MIN_VOL_USD", "75000"))
    TREND_MIN_LIQ_USD: float = float(os.getenv("TREND_MIN_LIQ_USD", "20000"))
    TREND_INTERVAL_SEC: int = int(os.getenv("TREND_INTERVAL_SEC", "60"))
    TREND_SOFT_FILL_MIN: int = int(os.getenv("TREND_SOFT_FILL_MIN", "6"))
    TREND_SOFT_FILL_SORT: str = os.getenv("TREND_SOFT_FILL_SORT", "vol24h")
    TREND_PER_BUY_FRACTION: float = float(os.getenv("TREND_PER_BUY_FRACTION", "0.05"))
    TREND_MIN_FREE_CASH_USD: float = float(os.getenv("TREND_MIN_FREE_CASH_USD", "50"))
    TREND_MAX_BUYS_PER_RUN: int = int(os.getenv("TREND_MAX_BUYS_PER_RUN", "5"))
    TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER: float = float(os.getenv("TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER", "1.3"))
    TRENDING_STOP_LOSS_FRACTION_FLOOR: float = float(os.getenv("TRENDING_STOP_LOSS_FRACTION_FLOOR", "0.06"))
    TRENDING_STOP_LOSS_FRACTION_CAP: float = float(os.getenv("TRENDING_STOP_LOSS_FRACTION_CAP", "0.25"))
    TRENDING_TP1_EXIT_FRACTION: float = float(os.getenv("TRENDING_TP1_EXIT_FRACTION", "0.15"))
    TRENDING_TP2_EXIT_FRACTION: float = float(os.getenv("TRENDING_TP2_EXIT_FRACTION", "0.30"))
    TRENDING_TP1_TAKE_PROFIT_FRACTION: float = float(os.getenv("TRENDING_TP1_TAKE_PROFIT_FRACTION", "0.35"))

    # Market data
    MARKETDATA_MAX_STALE_SECONDS: int = int(os.getenv("MARKETDATA_MAX_STALE_SECONDS", "180"))

    # Dexscreener client
    DEXSCREENER_BASE_URL: str = os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
    DEXSCREENER_FETCH_INTERVAL_SECONDS: int = int(os.getenv("DEXSCREENER_FETCH_INTERVAL_SECONDS", "10"))
    DEXSCREENER_MAX_ADDRESSES_PER_CALL: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES_PER_CALL", "20"))
    DEXSCREENER_MAX_ADDRESSES: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES", "1000"))
    DEXSCREENER_MIN_AGE_HOURS: float = float(os.getenv("DEXSCREENER_MIN_AGE_HOURS", "0.5"))
    DEXSCREENER_MAX_AGE_HOURS: float = float(os.getenv("DEXSCREENER_MAX_AGE_HOURS", "720"))
    DEXSCREENER_MAX_ABS_M5_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_M5_PCT", "25"))
    DEXSCREENER_MAX_ABS_H1_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_H1_PCT", "60"))
    DEXSCREENER_REBUY_COOLDOWN_MIN: int = int(os.getenv("DEXSCREENER_REBUY_COOLDOWN_MIN", "45"))

    # Cache
    CACHE_DIR: str = os.getenv("CACHE_DIR", "/app/data")
    CG_LIST_TTL_MIN: int = int(os.getenv("CG_LIST_TTL_MIN", "720"))

    # Scoring weights (sum can be arbitrary; they will be normalized at runtime)
    SCORE_WEIGHT_LIQUIDITY: float = float(os.getenv("SCORE_WEIGHT_LIQUIDITY", "1.0"))
    SCORE_WEIGHT_VOLUME: float = float(os.getenv("SCORE_WEIGHT_VOLUME", "1.0"))
    SCORE_WEIGHT_AGE: float = float(os.getenv("SCORE_WEIGHT_AGE", "0.7"))
    SCORE_WEIGHT_MOMENTUM: float = float(os.getenv("SCORE_WEIGHT_MOMENTUM", "1.3"))
    SCORE_WEIGHT_ORDER_FLOW: float = float(os.getenv("SCORE_WEIGHT_ORDER_FLOW", "1.0"))

    # --- Scoring thresholds (gates) ---
    SCORE_MIN_QUALITY: float = float(os.getenv("SCORE_MIN_QUALITY", "50"))
    SCORE_MIN_STATISTICS: float = float(os.getenv("SCORE_MIN_RANK", "55"))
    SCORE_MIN_ENTRY: float = float(os.getenv("SCORE_MIN_ENTRY", "60"))

    # AI adjustment config
    SCORE_AI_DELTA_MULTIPLIER: float = float(os.getenv("SCORE_AI_DELTA_MULTIPLIER", "1.5"))
    SCORE_AI_MAX_ABS_DELTA_POINTS: float = float(os.getenv("SCORE_AI_MAX_ABS_DELTA_POINTS", "20.0"))
    TOP_K_CANDIDATES_FOR_CHART_AI: int = int(os.getenv("TOP_K_CANDIDATES_FOR_CHART_AI", "12"))

    # OpenAI
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # ---- Chart-based AI Signal ----
    CHART_AI_ENABLED: bool = _as_bool(os.getenv("CHART_AI_ENABLED"), True)
    CHART_AI_SAVE_SCREENSHOTS: bool = _as_bool(os.getenv("CHART_AI_SAVE_SCREENSHOTS"), True)
    SCREENSHOT_DIR: str = os.getenv("SCREENSHOT_DIR", str(Path(__file__).resolve().parents[2] / "data" / "screenshots"))

    # Headless capture
    CHART_AI_TIMEFRAME: int = int(os.getenv("CHART_AI_TIMEFRAME", "5"))
    CHART_AI_LOOKBACK_MINUTES: int = int(os.getenv("CHART_AI_LOOKBACK_MINUTES", "120"))
    CHART_CAPTURE_TIMEOUT_SEC: int = int(os.getenv("CHART_CAPTURE_TIMEOUT_SEC", "15"))
    CHART_CAPTURE_VIEWPORT_WIDTH: int = int(os.getenv("CHART_CAPTURE_VIEWPORT_WIDTH", "1920"))
    CHART_CAPTURE_VIEWPORT_HEIGHT: int = int(os.getenv("CHART_CAPTURE_VIEWPORT_HEIGHT", "1080"))
    CHART_CAPTURE_HEADLESS: bool = _as_bool(os.getenv("CHART_CAPTURE_HEADLESS"), True)
    CHART_CAPTURE_BROWSER: str = os.getenv("CHART_CAPTURE_BROWSER", "chromium")
    CHART_CAPTURE_WAIT_CANVAS_MS: int = int(os.getenv("CHART_CAPTURE_WAIT_CANVAS_MS", "30000"))
    CHART_CAPTURE_AFTER_RENDER_MS: int = int(os.getenv("CHART_CAPTURE_AFTER_RENDER_MS", "900"))

    # Rate limiting / cache
    CHART_AI_MIN_CACHE_SECONDS: int = int(os.getenv("CHART_AI_MIN_CACHE_SECONDS", "60"))
    CHART_AI_MAX_REQUESTS_PER_MINUTE: int = int(os.getenv("CHART_AI_MAX_REQUESTS_PER_MINUTE", "10"))


settings = Settings()

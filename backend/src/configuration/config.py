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
    LOG_LEVEL_POSEIDON: str = os.getenv("LOG_LEVEL_POSEIDON", "DEBUG").upper()  # app packages
    LOG_LEVEL_LIB_REQUESTS: str = os.getenv("LOG_LEVEL_LIB_REQUESTS", "WARNING").upper()
    LOG_LEVEL_LIB_URLLIB3: str = os.getenv("LOG_LEVEL_LIB_URLLIB3", "WARNING".upper())
    LOG_LEVEL_LIB_WEB3: str = os.getenv("LOG_LEVEL_LIB_WEB3", "WARNING").upper()
    LOG_LEVEL_LIB_WEBSOCKETS: str = os.getenv("LOG_LEVEL_LIB_WEBSOCKETS", "WARNING").upper()
    LOG_LEVEL_LIB_HTTPX: str = os.getenv("LOG_LEVEL_LIB_HTTPX", "WARNING").upper()
    LOG_LEVEL_LIB_HTTPCORE: str = os.getenv("LOG_LEVEL_LIB_HTTPCORE", "WARNING").upper()
    LOG_LEVEL_LIB_ASYNCIO: str = os.getenv("LOG_LEVEL_LIB_ASYNCIO", "WARNING").upper()
    LOG_LEVEL_LIB_ANYIO: str = os.getenv("LOG_LEVEL_LIB_ANYIO", "WARNING").upper()

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Trending
    TREND_ENABLE: bool = _as_bool(os.getenv("TREND_ENABLE"), True)
    TREND_SOURCE: str = "cmc_dapi"
    TREND_INTERVAL: str = os.getenv("TREND_INTERVAL", "1h").lower()
    TREND_CATEGORY: str = os.getenv("TREND_CATEGORY", "Most Traded On-Chain")
    TREND_PAGE_SIZE: int = int(os.getenv("TREND_PAGE_SIZE", "100"))
    TREND_MAX_RESULTS: int = int(os.getenv("TREND_MAX_RESULTS", "100"))
    TREND_MIN_PCT_5M: float = float(os.getenv("TREND_MIN_PCT_5M", "2"))
    TREND_MIN_PCT_1H: float = float(os.getenv("TREND_MIN_PCT_1H", "5"))
    TREND_MIN_PCT_24H: float = float(os.getenv("TREND_MIN_PCT_24H", "10"))
    TREND_MIN_VOL_USD: float = float(os.getenv("TREND_MIN_VOL_USD", "100000"))
    TREND_MIN_LIQ_USD: float = float(os.getenv("TREND_MIN_LIQ_USD", "50000"))
    TREND_INTERVAL_SEC: int = int(os.getenv("TREND_INTERVAL_SEC", "60"))
    TREND_SOFT_FILL_MIN: int = int(os.getenv("TREND_SOFT_FILL_MIN", "6"))
    TREND_SOFT_FILL_SORT: str = os.getenv("TREND_SOFT_FILL_SORT", "vol24h")
    TREND_EXCLUDE_STABLES: bool = _as_bool(os.getenv("TREND_EXCLUDE_STABLES"), True)
    TREND_EXCLUDE_MAJORS: bool = _as_bool(os.getenv("TREND_EXCLUDE_MAJORS"), True)
    TREND_PER_BUY_USD: float = float(os.getenv("TREND_PER_BUY_USD", "200"))
    TREND_PER_BUY_FRACTION: float = float(os.getenv("TREND_PER_BUY_FRACTION", "0"))
    TREND_MIN_FREE_CASH_USD: float = float(os.getenv("TREND_MIN_FREE_CASH_USD", "50"))
    TREND_MAX_BUYS_PER_RUN: int = int(os.getenv("TREND_MAX_BUYS_PER_RUN", "5"))
    TREND_REQUIRE_DEX_PRICE: bool = _as_bool(os.getenv("TREND_REQUIRE_DEX_PRICE"), True)
    TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER: float = float(os.getenv("TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER", "3.0"))
    TRENDING_TP1_PCT: float = float(os.getenv("TRENDING_TP1_PCT", "0.15"))
    TRENDING_TP2_PCT: float = float(os.getenv("TRENDING_TP2_PCT", "0.30"))
    TRENDING_STOP_PCT: float = float(os.getenv("TRENDING_STOP_PCT", "0.2"))

    # Dexscreener client
    DEXSCREENER_BASE_URL: str = os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
    DEXSCREENER_FETCH_INTERVAL_SECONDS: int = int(os.getenv("DEXSCREENER_FETCH_INTERVAL_SECONDS", "10"))
    DEXSCREENER_MAX_ADDRESSES_PER_CALL: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES_PER_CALL", "20"))
    DEXSCREENER_MAX_ADDRESSES: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES", "1000"))
    DEXSCREENER_MIN_AGE_HOURS: float = float(os.getenv("DEXSCREENER_MIN_AGE_HOURS", "2"))
    DEXSCREENER_MAX_AGE_HOURS: float = float(os.getenv("DEXSCREENER_MAX_AGE_HOURS", "240"))
    DEXSCREENER_MAX_ABS_M5_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_M5_PCT", "25"))
    DEXSCREENER_MAX_ABS_H1_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_H1_PCT", "60"))
    DEXSCREENER_MIN_QUALITY_SCORE: float = float(os.getenv("DEXSCREENER_MIN_QUALITY_SCORE", "12"))
    DEXSCREENER_REBUY_COOLDOWN_MIN: int = int(os.getenv("DEXSCREENER_REBUY_COOLDOWN_MIN", "45"))

    # Cache
    CACHE_DIR: str = os.getenv("CACHE_DIR", "/app/data")
    CG_LIST_TTL_MIN: int = int(os.getenv("CG_LIST_TTL_MIN", "720"))


settings = Settings()

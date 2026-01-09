from __future__ import annotations

import os
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Parse a truthy/falsey string into a boolean."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_dict(settings: object) -> dict:
    """Return all UPPERCASE non-callable class attributes as a flat dict."""
    return {
        name: value
        for name, value in vars(settings.__class__).items()
        if name.isupper() and not callable(value)
    }


class Settings:
    # --- API ---
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # --- Core / modes ---
    PAPER_MODE: bool = _as_bool(os.getenv("PAPER_MODE"), True)
    TRADING_BOT_ENABLED: bool = _as_bool(os.getenv("TRADING_BOT_ENABLED"), True)
    PAPER_STARTING_CASH: float = float(os.getenv("PAPER_STARTING_CASH", "10000"))
    BASE_CURRENCY: str = os.getenv("BASE_CURRENCY", "EUR")

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", str(Path(__file__).resolve().parents[2] / "data" / "poseidon.db"))

    # --- Debug / logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "WARNING").upper()
    LOG_LEVEL_POSEIDON: str = os.getenv("LOG_LEVEL_POSEIDON", "DEBUG").upper()
    LOG_LEVEL_LIB_REQUESTS: str = os.getenv("LOG_LEVEL_LIB_REQUESTS", "WARNING").upper()
    LOG_LEVEL_LIB_URLLIB3: str = os.getenv("LOG_LEVEL_LIB_URLLIB3", "WARNING").upper()
    LOG_LEVEL_LIB_WEBSOCKETS: str = os.getenv("LOG_LEVEL_LIB_WEBSOCKETS", "WARNING").upper()
    LOG_LEVEL_LIB_HTTPX: str = os.getenv("LOG_LEVEL_LIB_HTTPX", "WARNING").upper()
    LOG_LEVEL_LIB_HTTPCORE: str = os.getenv("LOG_LEVEL_LIB_HTTPCORE", "WARNING").upper()
    LOG_LEVEL_LIB_ASYNCIO: str = os.getenv("LOG_LEVEL_LIB_ASYNCIO", "WARNING").upper()
    LOG_LEVEL_LIB_ANYIO: str = os.getenv("LOG_LEVEL_LIB_ANYIO", "WARNING").upper()
    LOG_LEVEL_LIB_OPENAI: str = os.getenv("LOG_LEVEL_LIB_OPENAI", "WARNING").upper()

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Trending ---
    TREND_ENABLE: bool = _as_bool(os.getenv("TREND_ENABLE"), True)
    TREND_INTERVAL: str = os.getenv("TREND_INTERVAL", "1h").lower()
    TREND_PAGE_SIZE: int = int(os.getenv("TREND_PAGE_SIZE", "100"))
    TREND_MAX_RESULTS: int = int(os.getenv("TREND_MAX_RESULTS", "100"))
    TREND_MIN_PCT_5M: float = float(os.getenv("TREND_MIN_PCT_5M", "2"))
    TREND_MIN_PCT_1H: float = float(os.getenv("TREND_MIN_PCT_1H", "5"))
    TREND_MIN_PCT_6H: float = float(os.getenv("TREND_MIN_PCT_6H", "8"))
    TREND_MIN_PCT_24H: float = float(os.getenv("TREND_MIN_PCT_24H", "10"))
    TREND_MIN_VOL5M_USD: float = float(os.getenv("TREND_MIN_VOL5M_USD", "5000"))
    TREND_MIN_VOL1H_USD: float = float(os.getenv("TREND_MIN_VOL1H_USD", "10000"))
    TREND_MIN_VOL6H_USD: float = float(os.getenv("TREND_MIN_VOL6H_USD", "25000"))
    TREND_MIN_VOL24H_USD: float = float(os.getenv("TREND_MIN_VOL24H_USD", "75000"))
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

    # --- Market data ---
    MARKETDATA_MAX_STALE_SECONDS: int = int(os.getenv("MARKETDATA_MAX_STALE_SECONDS", "180"))

    # --- Dexscreener client ---
    DEXSCREENER_BASE_URL: str = os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
    DEXSCREENER_FETCH_INTERVAL_SECONDS: int = int(os.getenv("DEXSCREENER_FETCH_INTERVAL_SECONDS", "10"))
    DEXSCREENER_MAX_ADDRESSES_PER_CALL: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES_PER_CALL", "20"))
    DEXSCREENER_MAX_ADDRESSES: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES", "1000"))
    DEXSCREENER_MIN_AGE_HOURS: float = float(os.getenv("DEXSCREENER_MIN_AGE_HOURS", "0.5"))
    DEXSCREENER_MAX_AGE_HOURS: float = float(os.getenv("DEXSCREENER_MAX_AGE_HOURS", "720"))
    DEXSCREENER_MAX_ABS_M5_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_M5_PCT", "25"))
    DEXSCREENER_MAX_ABS_H1_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_H1_PCT", "60"))
    DEXSCREENER_MAX_ABS_H6_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_H6_PCT", "120"))
    DEXSCREENER_MAX_ABS_H24_PCT: float = float(os.getenv("DEXSCREENER_MAX_ABS_H24_PCT", "200"))
    DEXSCREENER_REBUY_COOLDOWN_MIN: int = int(os.getenv("DEXSCREENER_REBUY_COOLDOWN_MIN", "45"))

    # --- Cache ---
    CACHE_DIR: str = os.getenv("CACHE_DIR", "/app/data")
    CG_LIST_TTL_MIN: int = int(os.getenv("CG_LIST_TTL_MIN", "720"))

    # --- Scoring weights (sum arbitrary; normalized at runtime) ---
    SCORE_WEIGHT_LIQUIDITY: float = float(os.getenv("SCORE_WEIGHT_LIQUIDITY", "1.0"))
    SCORE_WEIGHT_VOLUME: float = float(os.getenv("SCORE_WEIGHT_VOLUME", "1.0"))
    SCORE_WEIGHT_AGE: float = float(os.getenv("SCORE_WEIGHT_AGE", "0.7"))
    SCORE_WEIGHT_MOMENTUM: float = float(os.getenv("SCORE_WEIGHT_MOMENTUM", "1.3"))
    SCORE_WEIGHT_ORDER_FLOW: float = float(os.getenv("SCORE_WEIGHT_ORDER_FLOW", "1.0"))

    # --- Scoring thresholds (gates) ---
    SCORE_MIN_QUALITY: float = float(os.getenv("SCORE_MIN_QUALITY", "50"))
    SCORE_MIN_STATISTICS: float = float(os.getenv("SCORE_MIN_RANK", "55"))
    SCORE_MIN_ENTRY: float = float(os.getenv("SCORE_MIN_ENTRY", "60"))

    # --- AI adjustment config ---
    SCORE_AI_DELTA_MULTIPLIER: float = float(os.getenv("SCORE_AI_DELTA_MULTIPLIER", "1.5"))
    SCORE_AI_MAX_ABS_DELTA_POINTS: float = float(os.getenv("SCORE_AI_MAX_ABS_DELTA_POINTS", "20.0"))
    TOP_K_CANDIDATES_FOR_CHART_AI: int = int(os.getenv("TOP_K_CANDIDATES_FOR_CHART_AI", "12"))

    # --- OpenAI ---
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # --- Chart-based AI Signal ---
    CHART_AI_ENABLED: bool = _as_bool(os.getenv("CHART_AI_ENABLED"), True)
    CHART_AI_SAVE_SCREENSHOTS: bool = _as_bool(os.getenv("CHART_AI_SAVE_SCREENSHOTS"), True)
    SCREENSHOT_DIR: str = os.getenv("SCREENSHOT_DIR", str(Path(__file__).resolve().parents[2] / "data" / "screenshots"))

    # --- Headless capture ---
    CHART_AI_TIMEFRAME: int = int(os.getenv("CHART_AI_TIMEFRAME", "5"))
    CHART_AI_LOOKBACK_MINUTES: int = int(os.getenv("CHART_AI_LOOKBACK_MINUTES", "120"))
    CHART_CAPTURE_TIMEOUT_SEC: int = int(os.getenv("CHART_CAPTURE_TIMEOUT_SEC", "15"))
    CHART_CAPTURE_VIEWPORT_WIDTH: int = int(os.getenv("CHART_CAPTURE_VIEWPORT_WIDTH", "1280"))
    CHART_CAPTURE_VIEWPORT_HEIGHT: int = int(os.getenv("CHART_CAPTURE_VIEWPORT_HEIGHT", "720"))
    CHART_CAPTURE_HEADLESS: bool = _as_bool(os.getenv("CHART_CAPTURE_HEADLESS"), True)
    CHART_CAPTURE_BROWSER: str = os.getenv("CHART_CAPTURE_BROWSER", "chromium")
    CHART_CAPTURE_WAIT_CANVAS_MS: int = int(os.getenv("CHART_CAPTURE_WAIT_CANVAS_MS", "30000"))
    CHART_CAPTURE_AFTER_RENDER_MS: int = int(os.getenv("CHART_CAPTURE_AFTER_RENDER_MS", "900"))

    # --- Rate limiting / cache ---
    CHART_AI_MIN_CACHE_SECONDS: int = int(os.getenv("CHART_AI_MIN_CACHE_SECONDS", "60"))
    CHART_AI_MAX_REQUESTS_PER_MINUTE: int = int(os.getenv("CHART_AI_MAX_REQUESTS_PER_MINUTE", "10"))

    # --- On-chain settings ---
    WETH_ADDRESS: str = os.getenv("WETH_ADDRESS", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    EVM_RPC_URL: str = os.getenv("EVM_RPC_URL", "")
    EVM_MNEMONIC: str = os.getenv("EVM_MNEMONIC", "")
    EVM_DERIVATION_INDEX: int = int(os.getenv("EVM_DERIVATION_INDEX", "0"))
    SOLANA_RPC_URL: str = os.getenv("SOLANA_RPC_URL", "")
    SOLANA_SECRET_KEY_BASE58: str = os.getenv("SOLANA_SECRET_KEY_BASE58", "")
    LIFI_BASE_URL: str = os.getenv("LIFI_BASE_URL", "https://li.quest")

    # --- Consistency guard (Dexscreener) ---
    DEX_INCONSISTENCY_WINDOW_SIZE: int = int(os.getenv("DEX_INCONSISTENCY_WINDOW_SIZE", "6"))
    DEX_INCONSISTENCY_ALTERNATION_CYCLES: int = int(os.getenv("DEX_INCONSISTENCY_ALTERNATION_CYCLES", "2"))
    DEX_INCONSISTENCY_JUMP_FACTOR: float = float(os.getenv("DEX_INCONSISTENCY_MAX_PRICE_JUMP", "5"))
    DEX_INCONSISTENCY_FIELDS_MISMATCH_MIN: int = int(os.getenv("DEX_INCONSISTENCY_FIELDS_MISMATCH_MIN", "2"))

    # --- Aave / Lending ---
    AVALANCHE_RPC_URL: str = os.getenv("AVALANCHE_RPC_URL", "https://api.avax.network/ext/bc/C/rpc")
    AAVE_POOL_V3_ADDRESS: str = os.getenv("AAVE_POOL_V3_ADDRESS", "0x794a61358D6845594F94dc1DB02A252b5b4814aD")
    AAVE_USDC_ADDRESS: str = os.getenv("AAVE_USDC_ADDRESS", "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E")
    AAVE_MNEMONIC: str = os.getenv("AAVE_MNEMONIC", "")
    AAVE_DERIVATION_INDEX: int = int(os.getenv("AAVE_DERIVATION_INDEX", "0"))
    AAVE_INITIAL_DEPOSIT_USD: float = float(os.getenv("AAVE_INITIAL_DEPOSIT_USD", "0.0"))
    AAVE_REPORTING_INTERVAL_SECONDS: int = int(os.getenv("AAVE_REPORTING_INTERVAL_SECONDS", "60"))

    # --- Aave Sentinel Logic ---
    AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD", "1.40"))
    AAVE_HEALTH_FACTOR_WARNING_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_WARNING_THRESHOLD", "1.25"))
    AAVE_HEALTH_FACTOR_DANGER_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_DANGER_THRESHOLD", "1.15"))
    AAVE_HEALTH_FACTOR_EMERGENCY_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_EMERGENCY_THRESHOLD", "1.03"))
    AAVE_ALERT_COOLDOWN_SECONDS: int = int(os.getenv("AAVE_ALERT_COOLDOWN_SECONDS", "3600"))
    AAVE_SIGNIFICANT_DEVIATION_HF: float = float(os.getenv("AAVE_SIGNIFICANT_DEVIATION_HF", "0.05"))
    AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT: float = float(os.getenv("AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT", "0.10"))
    AAVE_RESCUE_TARGET_HF_IMPROVEMENT: float = float(os.getenv("AAVE_RESCUE_TARGET_HF_IMPROVEMENT", "0.05"))
    AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD: float = float(os.getenv("AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD", "0.80"))
    AAVE_RESCUE_MIN_AMOUNT_USDC: float = float(os.getenv("AAVE_RESCUE_MIN_AMOUNT_USDC", "10.0"))
    AAVE_RESCUE_MAX_CAP_USDC: float = float(os.getenv("AAVE_RESCUE_MAX_CAP_USDC", "1000.0"))


settings: Settings = Settings()
from __future__ import annotations

import os
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_dict(settings: object) -> dict:
    return {
        name: value
        for name, value in vars(settings.__class__).items()
        if name.isupper() and not callable(value)
    }


class Settings:
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    PAPER_MODE: bool = _as_bool(os.getenv("PAPER_MODE"), True)
    PAPER_STARTING_CASH: float = float(os.getenv("PAPER_STARTING_CASH", "10000"))
    BASE_CURRENCY: str = os.getenv("BASE_CURRENCY", "EUR")

    DATABASE_URL: str = os.getenv("DATABASE_URL", str(Path(__file__).resolve().parents[2] / "data" / "poseidon.db"))

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

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_POLL_INTERVAL_SECONDS: float = float(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "2.0"))

    TRADING_ENABLED: bool = _as_bool(os.getenv("TRADING_ENABLED"), False)
    TRADING_SCAN_INTERVAL: str = os.getenv("TRADING_SCAN_INTERVAL", "5m").lower()
    TRADING_PAGE_SIZE: int = int(os.getenv("TRADING_PAGE_SIZE", "100"))
    TRADING_MAX_RESULTS: int = int(os.getenv("TRADING_MAX_RESULTS", "100"))
    TRADING_MAX_OPEN_POSITIONS: int = int(os.getenv("TRADING_MAX_OPEN_POSITIONS", "30"))
    TRADING_MIN_PERCENT_CHANGE_5M: float = float(os.getenv("TRADING_MIN_PERCENT_CHANGE_5M", "2"))
    TRADING_MIN_PERCENT_CHANGE_1H: float = float(os.getenv("TRADING_MIN_PERCENT_CHANGE_1H", "5"))
    TRADING_MIN_PERCENT_CHANGE_6H: float = float(os.getenv("TRADING_MIN_PERCENT_CHANGE_6H", "8"))
    TRADING_MIN_PERCENT_CHANGE_24H: float = float(os.getenv("TRADING_MIN_PERCENT_CHANGE_24H", "10"))
    TRADING_MIN_VOLUME_5M_USD: float = float(os.getenv("TRADING_MIN_VOLUME_5M_USD", "5000"))
    TRADING_MIN_VOLUME_1H_USD: float = float(os.getenv("TRADING_MIN_VOLUME_1H_USD", "25000"))
    TRADING_MIN_VOLUME_6H_USD: float = float(os.getenv("TRADING_MIN_VOLUME_6H_USD", "25000"))
    TRADING_MIN_VOLUME_24H_USD: float = float(os.getenv("TRADING_MIN_VOLUME_24H_USD", "90000"))
    TRADING_MIN_LIQUIDITY_USD: float = float(os.getenv("TRADING_MIN_LIQUIDITY_USD", "30000"))
    TRADING_LOOP_INTERVAL_SECONDS: int = int(os.getenv("TRADING_LOOP_INTERVAL_SECONDS", "60"))
    TRADING_PER_BUY_FRACTION: float = float(os.getenv("TRADING_PER_BUY_FRACTION", "0.05"))
    TRADING_MIN_FREE_CASH_USD: float = float(os.getenv("TRADING_MIN_FREE_CASH_USD", "200"))
    TRADING_MAX_PRICE_DEVIATION_MULTIPLIER: float = float(os.getenv("TRADING_MAX_PRICE_DEVIATION_MULTIPLIER", "1.10"))
    TRADING_SLIPPAGE_TOLERANCE: float = float(os.getenv("TRADING_SLIPPAGE_TOLERANCE", "0.03"))
    TRADING_STOP_LOSS_FRACTION_FLOOR: float = float(os.getenv("TRADING_STOP_LOSS_FRACTION_FLOOR", "0.08"))
    TRADING_STOP_LOSS_FRACTION_CAP: float = float(os.getenv("TRADING_STOP_LOSS_FRACTION_CAP", "0.20"))
    TRADING_TP1_EXIT_FRACTION: float = float(os.getenv("TRADING_TP1_EXIT_FRACTION", "0.10"))
    TRADING_TP2_EXIT_FRACTION: float = float(os.getenv("TRADING_TP2_EXIT_FRACTION", "0.20"))
    TRADING_RISK_STOP_LOSS_VOLATILITY_MULTIPLIER: float = float(os.getenv("TRADING_RISK_STOP_LOSS_VOLATILITY_MULTIPLIER", "1.8"))
    TRADING_RISK_CONFIDENCE_MULTIPLIER_MIN: float = float(os.getenv("TRADING_RISK_CONFIDENCE_MULTIPLIER_MIN", "0.5"))
    TRADING_RISK_CONFIDENCE_MULTIPLIER_MAX: float = float(os.getenv("TRADING_RISK_CONFIDENCE_MULTIPLIER_MAX", "2.0"))
    TRADING_RISK_CONFIDENCE_MOMENTUM_BASELINE: float = float(os.getenv("TRADING_RISK_CONFIDENCE_MOMENTUM_BASELINE", "60.0"))
    TRADING_RISK_CONFIDENCE_MOMENTUM_DIVISOR: float = float(os.getenv("TRADING_RISK_CONFIDENCE_MOMENTUM_DIVISOR", "100.0"))
    TRADING_RISK_UNCERTAINTY_PENALTY_MULTIPLIER: float = float(os.getenv("TRADING_RISK_UNCERTAINTY_PENALTY_MULTIPLIER", "2.0"))
    TRADING_TP1_TAKE_PROFIT_FRACTION: float = float(os.getenv("TRADING_TP1_TAKE_PROFIT_FRACTION", "0.50"))
    TRADING_MIN_AGE_HOURS: float = float(os.getenv("TRADING_MIN_AGE_HOURS", "1"))
    TRADING_MAX_AGE_HOURS: float = float(os.getenv("TRADING_MAX_AGE_HOURS", "164"))
    TRADING_MAX_ABSOLUTE_PERCENT_5M: float = float(os.getenv("TRADING_MAX_ABSOLUTE_PERCENT_5M", "8"))
    TRADING_MAX_ABSOLUTE_PERCENT_1H: float = float(os.getenv("TRADING_MAX_ABSOLUTE_PERCENT_1H", "40"))
    TRADING_MAX_ABSOLUTE_PERCENT_6H: float = float(os.getenv("TRADING_MAX_ABSOLUTE_PERCENT_6H", "100"))
    TRADING_MAX_ABSOLUTE_PERCENT_24H: float = float(os.getenv("TRADING_MAX_ABSOLUTE_PERCENT_24H", "150"))
    TRADING_REBUY_COOLDOWN_MINUTES: int = int(os.getenv("TRADING_REBUY_COOLDOWN_MINUTES", "45"))
    TRADING_ALLOWED_CHAINS: list[str] = os.getenv("TRADING_ALLOWED_CHAINS", "solana,bsc,base").lower().split(",")

    TRADING_MIN_FDV_USD: float = float(os.getenv("TRADING_MIN_FDV_USD", "100000"))
    TRADING_MAX_FDV_USD: float = float(os.getenv("TRADING_MAX_FDV_USD", "40000000"))
    TRADING_MIN_MARKET_CAP_USD: float = float(os.getenv("TRADING_MIN_MARKET_CAP_USD", "30000"))
    TRADING_MAX_MARKET_CAP_USD: float = float(os.getenv("TRADING_MAX_MARKET_CAP_USD", "30000000"))
    TRADING_MIN_LIQUIDITY_TO_FDV_RATIO: float = float(os.getenv("TRADING_MIN_LIQUIDITY_TO_FDV_RATIO", "0.03"))

    TRADING_RISK_WEAK_BUY_FLOW_RATIO: float = float(os.getenv("TRADING_RISK_WEAK_BUY_FLOW_RATIO", "0.60"))
    TRADING_RISK_WEAK_BUY_FLOW_MIN_PERCENT_5M: float = float(os.getenv("TRADING_RISK_WEAK_BUY_FLOW_MIN_PERCENT_5M", "6.0"))
    TRADING_RISK_OVEREXTENDED_FACTOR: float = float(os.getenv("TRADING_RISK_OVEREXTENDED_FACTOR", "0.7"))

    TRADING_SCORE_WEIGHT_LIQUIDITY: float = float(os.getenv("TRADING_SCORE_WEIGHT_LIQUIDITY", "1.0"))
    TRADING_SCORE_WEIGHT_VOLUME: float = float(os.getenv("TRADING_SCORE_WEIGHT_VOLUME", "1.0"))
    TRADING_SCORE_WEIGHT_AGE: float = float(os.getenv("TRADING_SCORE_WEIGHT_AGE", "1.3"))
    TRADING_SCORE_WEIGHT_MOMENTUM: float = float(os.getenv("TRADING_SCORE_WEIGHT_MOMENTUM", "1.3"))
    TRADING_SCORE_WEIGHT_ORDER_FLOW: float = float(os.getenv("TRADING_SCORE_WEIGHT_ORDER_FLOW", "1.0"))
    TRADING_SCORE_MIN_QUALITY: float = float(os.getenv("TRADING_SCORE_MIN_QUALITY", "20"))
    TRADING_SCORE_MIN_STATISTICS: float = float(os.getenv("TRADING_SCORE_MIN_STATISTICS", "60"))
    TRADING_SCORE_MIN_ENTRY: float = float(os.getenv("TRADING_SCORE_MIN_ENTRY", "60"))
    TRADING_AI_DELTA_MULTIPLIER: float = float(os.getenv("TRADING_AI_DELTA_MULTIPLIER", "1.0"))
    TRADING_AI_MAX_ABSOLUTE_DELTA_POINTS: float = float(os.getenv("TRADING_AI_MAX_ABSOLUTE_DELTA_POINTS", "12.0"))
    TRADING_AI_TOP_K_CANDIDATES: int = int(os.getenv("TRADING_AI_TOP_K_CANDIDATES", "12"))
    TRADING_AI_ENABLED: bool = _as_bool(os.getenv("TRADING_AI_ENABLED"), False)
    TRADING_AI_TIMEFRAME_MINUTES: int = int(os.getenv("TRADING_AI_TIMEFRAME_MINUTES", "5"))
    TRADING_AI_LOOKBACK_MINUTES: int = int(os.getenv("TRADING_AI_LOOKBACK_MINUTES", "120"))

    TRADING_INCONSISTENCY_WINDOW_SIZE: int = int(os.getenv("TRADING_INCONSISTENCY_WINDOW_SIZE", "6"))
    TRADING_INCONSISTENCY_ALTERNATION_CYCLES: int = int(os.getenv("TRADING_INCONSISTENCY_ALTERNATION_CYCLES", "2"))
    TRADING_INCONSISTENCY_JUMP_FACTOR: float = float(os.getenv("TRADING_INCONSISTENCY_JUMP_FACTOR", "5"))
    TRADING_INCONSISTENCY_FIELDS_MISMATCH_MIN: int = int(os.getenv("TRADING_INCONSISTENCY_FIELDS_MISMATCH_MIN", "2"))

    MARKETDATA_MAX_STALE_SECONDS: int = int(os.getenv("MARKETDATA_MAX_STALE_SECONDS", "180"))

    DEXSCREENER_BASE_URL: str = os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
    DEXSCREENER_FETCH_INTERVAL_SECONDS: int = int(os.getenv("DEXSCREENER_FETCH_INTERVAL_SECONDS", "10"))
    DEXSCREENER_MAX_ADDRESSES_PER_CALL: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES_PER_CALL", "20"))
    DEXSCREENER_MAX_ADDRESSES: int = int(os.getenv("DEXSCREENER_MAX_ADDRESSES", "1000"))

    CACHE_DIR: str = os.getenv("CACHE_DIR", "/app/data")
    CG_LIST_TTL_MIN: int = int(os.getenv("CG_LIST_TTL_MIN", "720"))

    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    CHART_AI_SAVE_SCREENSHOTS: bool = _as_bool(os.getenv("CHART_AI_SAVE_SCREENSHOTS"), True)
    SCREENSHOT_DIR: str = os.getenv("SCREENSHOT_DIR", str(Path(__file__).resolve().parents[2] / "data" / "screenshots"))
    CHART_CAPTURE_TIMEOUT_SEC: int = int(os.getenv("CHART_CAPTURE_TIMEOUT_SEC", "15"))
    CHART_CAPTURE_VIEWPORT_WIDTH: int = int(os.getenv("CHART_CAPTURE_VIEWPORT_WIDTH", "1280"))
    CHART_CAPTURE_VIEWPORT_HEIGHT: int = int(os.getenv("CHART_CAPTURE_VIEWPORT_HEIGHT", "720"))
    CHART_CAPTURE_HEADLESS: bool = _as_bool(os.getenv("CHART_CAPTURE_HEADLESS"), True)
    CHART_CAPTURE_BROWSER: str = os.getenv("CHART_CAPTURE_BROWSER", "chromium")
    CHART_CAPTURE_WAIT_CANVAS_MS: int = int(os.getenv("CHART_CAPTURE_WAIT_CANVAS_MS", "30000"))
    CHART_CAPTURE_AFTER_RENDER_MS: int = int(os.getenv("CHART_CAPTURE_AFTER_RENDER_MS", "900"))
    CHART_AI_MIN_CACHE_SECONDS: int = int(os.getenv("CHART_AI_MIN_CACHE_SECONDS", "60"))
    CHART_AI_MAX_REQUESTS_PER_MINUTE: int = int(os.getenv("CHART_AI_MAX_REQUESTS_PER_MINUTE", "10"))

    WALLET_MNEMONIC: str = os.getenv("WALLET_MNEMONIC", "")
    WALLET_DERIVATION_INDEX: int = int(os.getenv("WALLET_DERIVATION_INDEX", "0"))

    SOLANA_RPC_URL: str = os.getenv("SOLANA_RPC_URL", "")
    EVM_RPC_URL: str = os.getenv("EVM_RPC_URL", "")
    BSC_RPC_URL: str = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
    BASE_RPC_URL: str = os.getenv("BASE_RPC_URL", "")
    AVALANCHE_RPC_URL: str = os.getenv("AVALANCHE_RPC_URL", "https://api.avax.network/ext/bc/C/rpc")

    WETH_ADDRESS: str = os.getenv("WETH_ADDRESS", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    LIFI_BASE_URL: str = os.getenv("LIFI_BASE_URL", "https://li.quest")

    AAVE_POOL_V3_ADDRESS: str = os.getenv("AAVE_POOL_V3_ADDRESS", "0x794a61358D6845594F94dc1DB02A252b5b4814aD")
    AAVE_USDC_ADDRESS: str = os.getenv("AAVE_USDC_ADDRESS", "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E")
    AAVE_BTCB_ADDRESS: str = os.getenv("AAVE_BTCB_ADDRESS", "0x152b9d0FdC40C096757F570A51E494bd4b943E50")

    AAVE_INITIAL_DEPOSIT_USD: float = float(os.getenv("AAVE_INITIAL_DEPOSIT_USD", "0.0"))
    AAVE_REPORTING_INTERVAL_SECONDS: int = int(os.getenv("AAVE_REPORTING_INTERVAL_SECONDS", "60"))
    AAVE_MAX_CONCURRENT_ASSET_SCANS: int = int(os.getenv("AAVE_MAX_CONCURRENT_ASSET_SCANS", "5"))

    AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD", "1.45"))
    AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD", "1.35"))
    AAVE_HEALTH_FACTOR_WARNING_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_WARNING_THRESHOLD", "1.25"))
    AAVE_HEALTH_FACTOR_DANGER_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_DANGER_THRESHOLD", "1.15"))
    AAVE_HEALTH_FACTOR_EMERGENCY_THRESHOLD: float = float(os.getenv("AAVE_HEALTH_FACTOR_EMERGENCY_THRESHOLD", "1.05"))
    AAVE_ALERT_COOLDOWN_SECONDS: int = int(os.getenv("AAVE_ALERT_COOLDOWN_SECONDS", "3600"))
    AAVE_SIGNIFICANT_DEVIATION_HF: float = float(os.getenv("AAVE_SIGNIFICANT_DEVIATION_HF", "0.05"))
    AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT: float = float(os.getenv("AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT", "0.10"))
    AAVE_RESCUE_TARGET_HF_IMPROVEMENT: float = float(os.getenv("AAVE_RESCUE_TARGET_HF_IMPROVEMENT", "0.05"))
    AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD: float = float(os.getenv("AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD", "0.80"))
    AAVE_RESCUE_MIN_AMOUNT_USDC: float = float(os.getenv("AAVE_RESCUE_MIN_AMOUNT_USDC", "10.0"))
    AAVE_RESCUE_MAX_CAP_USDC: float = float(os.getenv("AAVE_RESCUE_MAX_CAP_USDC", "1000.0"))

    AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS: int = int(os.getenv("AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS", "10"))
    AAVE_DCA_EMA50_WARMUP_KLINES: int = int(os.getenv("AAVE_DCA_EMA50_WARMUP_KLINES", "150"))

    MACRO_CURRENT_CYCLE_INDEX: int = 5
    MACRO_PREVIOUS_ATH: float = 125000
    MACRO_PREVIOUS_BULL_AMPLITUDE_PCT: float = 680
    MACRO_FLATTENING_FACTOR: float = 3
    MACRO_BEAR_BOTTOM_MULTIPLIER: float = 0.30
    MACRO_MINIMUM_BULL_MULTIPLIER: float = 1.20
    AAVE_ESTIMATED_APY: float = 0.05


settings: Settings = Settings()

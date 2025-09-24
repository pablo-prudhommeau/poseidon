import os

def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

class Settings:
    PAPER_MODE: bool = (os.getenv("PAPER_MODE", "true").lower() in ("1","true","yes"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL","INFO").upper()
    BASE_CURRENCY: str = os.getenv("BASE_CURRENCY","EUR")

    QUICKNODE_URL: str = os.getenv("QUICKNODE_URL","")
    UNISWAP_FACTORY_ADDRESS: str = os.getenv("UNISWAP_FACTORY_ADDRESS","0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f")
    WETH_ADDRESS: str = os.getenv("WETH_ADDRESS","0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")

     # Verbosité détaillée (debug)
    DEBUG_SAMPLE_ROWS: int = int(os.getenv("DEBUG_SAMPLE_ROWS", "8"))  # combien d’items à détailler
    DEBUG_HTTP: bool = _as_bool(os.getenv("DEBUG_HTTP"), False)        # log des URLs/params HTTP
    LOG_LEVEL_LIB_REQUESTS: str = os.getenv("LOG_LEVEL_LIB_REQUESTS", "WARNING").upper()
    LOG_LEVEL_LIB_WEB3: str = os.getenv("LOG_LEVEL_LIB_WEB3", "WARNING").upper()

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN","")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID","")

    # Liquidity momentum
    LIQ_POLL_SEC: int = int(os.getenv("LIQ_POLL_SEC","30"))
    LIQ_LOOKBACK_SEC: int = int(os.getenv("LIQ_LOOKBACK_SEC","600"))
    LIQ_MIN_WETH_ETH: float = float(os.getenv("LIQ_MIN_WETH_ETH","0.8"))
    LIQ_MIN_GROWTH_BPS: int = int(os.getenv("LIQ_MIN_GROWTH_BPS","300"))
    LIQ_TRACK_LIMIT: int = int(os.getenv("LIQ_TRACK_LIMIT","200"))
    LIQ_ALERT_COOLDOWN_SEC: int = int(os.getenv("LIQ_ALERT_COOLDOWN_SEC","900"))

    # OFFCHAIN — CMC DAPI trending
    TREND_ENABLE: bool = _as_bool(os.getenv("TREND_ENABLE"), True)
    TREND_SOURCE: str = "cmc_dapi"  # unique
    TREND_INTERVAL: str = os.getenv("TREND_INTERVAL", "1h").lower()  # 5m | 1h | 4h | 24h
    TREND_CATEGORY: str = os.getenv("TREND_CATEGORY", "Most Traded On-Chain")

    # >>> ETH only via DAPI <<<
    TREND_CHAIN: str = os.getenv("TREND_CHAIN", "ethereum").lower()   # chaîne texte attendue par dapi
    TREND_CHAIN_ID: str = os.getenv("TREND_CHAIN_ID", "1")            # fallback si dapi préfère l'id

    TREND_PAGE_SIZE: int = int(os.getenv("TREND_PAGE_SIZE", "100"))
    TREND_MAX_RESULTS: int = int(os.getenv("TREND_MAX_RESULTS", "10"))

    # Seuils (adapte selon l’intervalle)
    TREND_MIN_PCT_5M: float = float(os.getenv("TREND_MIN_PCT_5M", "2"))
    TREND_MIN_PCT_1H: float = float(os.getenv("TREND_MIN_PCT_1H", "5"))
    TREND_MIN_PCT_24H: float = float(os.getenv("TREND_MIN_PCT_24H", "10"))
    TREND_MIN_VOL_USD: float = float(os.getenv("TREND_MIN_VOL_USD", "100000"))
    TREND_MIN_LIQ_USD: float = float(os.getenv("TREND_MIN_LIQ_USD", "50000"))

    TREND_INTERVAL_SEC: int = int(os.getenv("TREND_INTERVAL_SEC", "180"))
    TREND_POLL_SEC= int(os.getenv("TREND_POLL_SEC", "180"))  # fréquence du scan offchain

    TREND_SOFTFILL_MIN = int(os.getenv("TREND_SOFTFILL_MIN", "6"))  # nb min à renvoyer
    TREND_SOFTFILL_SORT = os.getenv("TREND_SOFTFILL_SORT", "vol24h")  # ou "liqUsd"

    TREND_EXCLUDE_STABLES: bool = _as_bool(os.getenv("TREND_EXCLUDE_STABLES"), True)
    TREND_EXCLUDE_MAJORS: bool = _as_bool(os.getenv("TREND_EXCLUDE_MAJORS"), True)

    # Cache
    CACHE_DIR: str = os.getenv("CACHE_DIR","/app/data")
    CG_LIST_TTL_MIN: int = int(os.getenv("CG_LIST_TTL_MIN","720"))

settings = Settings()

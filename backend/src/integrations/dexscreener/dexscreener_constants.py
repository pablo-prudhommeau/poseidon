from typing import Union, Dict, List

from src.configuration.config import settings

BASE_URL: str = settings.DEXSCREENER_BASE_URL.rstrip("/")
LATEST_TOKENS_ENDPOINT: str = f"{BASE_URL}/latest/dex/tokens"
TOKEN_PROFILES_ENDPOINT: str = f"{BASE_URL}/token-profiles/latest/v1"
TOKEN_BOOSTS_LATEST_ENDPOINT: str = f"{BASE_URL}/token-boosts/latest/v1"
TOKEN_BOOSTS_TOP_ENDPOINT: str = f"{BASE_URL}/token-boosts/top/v1"

DEFAULT_MAX_ADDRESSES_PER_CALL: int = max(1, int(settings.DEXSCREENER_MAX_ADDRESSES_PER_CALL))
TOTAL_ADDRESS_HARD_CAP: int = max(1, int(settings.DEXSCREENER_MAX_ADDRESSES))
HTTP_TIMEOUT_SECONDS: float = 15.0

JSONScalar = Union[str, int, float, bool, None]
JSON = Union[JSONScalar, Dict[str, "JSON"], List["JSON"]]

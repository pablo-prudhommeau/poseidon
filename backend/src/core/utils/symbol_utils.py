from typing import Dict, Set, Any, Optional

_NATIVE_SYMBOL_SYNONYMS: Dict[str, Set[str]] = {
    "ethereum": {"ETH", "WETH"},
    "arbitrum": {"ETH", "WETH"},
    "optimism": {"ETH", "WETH"},
    "base": {"ETH", "WETH"},
    "linea": {"ETH", "WETH"},
    "scroll": {"ETH", "WETH"},
    "blast": {"ETH", "WETH"},
    "zksync": {"ETH", "WETH"},
    "polygon-zkevm": {"ETH", "WETH"},
    "polygon_zkevm": {"ETH", "WETH"},
    "era": {"ETH", "WETH"},
    "bsc": {"BNB", "WBNB"},
    "opbnb": {"BNB", "WBNB"},
    "polygon": {"MATIC", "WMATIC"},
    "avalanche": {"AVAX", "WAVAX"},
    "fantom": {"FTM", "WFTM"},
    "cronos": {"CRO", "WCRO"},
    "gnosis": {"XDAI", "WXDAI"},
    "celo": {"CELO", "WCELO"},
    "metis": {"METIS", "WMETIS"},
    "mantle": {"MNT", "WMNT"},
    "kava": {"KAVA", "WKAVA"},
    "moonbeam": {"GLMR", "WGLMR"},
    "moonriver": {"MOVR", "WMOVR"},
}


def _get_symbol(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    sym = obj.get("symbol") or obj.get("sym") or obj.get("ticker")
    return str(sym).strip().upper() if isinstance(sym, str) else ""


def _get_address(obj: Any) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    addr = obj.get("address") or obj.get("addr")
    return str(addr) if isinstance(addr, str) and addr else None


def _native_synonyms(chain_key: str) -> Set[str]:
    return _NATIVE_SYMBOL_SYNONYMS.get(chain_key.strip().lower(), {"ETH", "WETH"})


def _is_native_symbol(symbol: str, chain_key: str) -> bool:
    return symbol.upper() in _native_synonyms(chain_key)

from __future__ import annotations

"""
LI.FI lightweight client for same-chain quotes and execution helpers.

Key points:
- Supports *EVM only* (same-chain native -> ERC20).
- When LI.FI filters a route due to high price impact (>10%), we
  automatically reduce the order size and retry a few times until
  a quote is accepted, or a minimum USD threshold is reached.

Environment:
    settings.LIFI_BASE_URL

Public API:
    - is_supported_evm_chain_key(chain_key: str) -> bool
    - resolve_lifi_chain_id(chain_key: str) -> int | None
    - build_native_to_token_quote(...): Dict
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import json
import math

import httpx

from src.configuration.config import settings
from src.logging.logger import get_logger
from src.integrations.native_price_provider import get_native_price_usd

log = get_logger(__name__)

# Per LI.FI docs: native token on EVM = 0x000...000
EVM_NATIVE_TOKEN_ZERO_ADDRESS: str = "0x0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class EvmChain:
    """Canonical mapping entry for an EVM chain supported by Dexscreener and LI.FI."""
    dexscreener_key: str
    chain_id: int
    native_symbol: str


# --------------------------------------------------------------------------
# Chain registry (Dexscreener key -> LI.FI EVM chain id)
# --------------------------------------------------------------------------
_EVM_CHAIN_REGISTRY: Dict[str, EvmChain] = {
    # ETH-based
    "ethereum": EvmChain("ethereum", 1, "ETH"),
    "arbitrum": EvmChain("arbitrum", 42161, "ETH"),
    "optimism": EvmChain("optimism", 10, "ETH"),
    "base": EvmChain("base", 8453, "ETH"),
    "linea": EvmChain("linea", 59144, "ETH"),
    "scroll": EvmChain("scroll", 534352, "ETH"),
    "blast": EvmChain("blast", 81457, "ETH"),
    "zksync": EvmChain("zksync", 324, "ETH"),
    "era": EvmChain("era", 324, "ETH"),  # some feeds label zkSync as 'era'
    "polygon-zkevm": EvmChain("polygon-zkevm", 1101, "ETH"),
    "polygon_zkevm": EvmChain("polygon_zkevm", 1101, "ETH"),

    # Alt-native EVMs
    "bsc": EvmChain("bsc", 56, "BNB"),
    "opbnb": EvmChain("opbnb", 204, "BNB"),
    "polygon": EvmChain("polygon", 137, "MATIC"),
    "avalanche": EvmChain("avalanche", 43114, "AVAX"),
    "fantom": EvmChain("fantom", 250, "FTM"),
    "cronos": EvmChain("cronos", 25, "CRO"),
    "gnosis": EvmChain("gnosis", 100, "xDAI"),
    "celo": EvmChain("celo", 42220, "CELO"),
    "metis": EvmChain("metis", 1088, "METIS"),
    "mantle": EvmChain("mantle", 5000, "MNT"),
    "kava": EvmChain("kava", 2222, "KAVA"),
    "moonbeam": EvmChain("moonbeam", 1284, "GLMR"),
    "moonriver": EvmChain("moonriver", 1285, "MOVR"),
}


def _normalize_chain_key(raw: str | None) -> str:
    """Normalize incoming chain keys from Dexscreener for robust lookups."""
    if not raw:
        return ""
    key = raw.strip().lower()

    # Common aliases / normalizations
    if key in {"eth", "ethereum-mainnet"}:
        return "ethereum"
    if key in {"arb", "arbitrum-one"}:
        return "arbitrum"
    if key in {"op", "optimism-mainnet"}:
        return "optimism"
    if key in {"bsc-mainnet", "binance-smart-chain", "binance"}:
        return "bsc"
    if key in {"matic", "polygon-pos", "polygon-mainnet"}:
        return "polygon"
    if key in {"avax", "avalanche-c"}:
        return "avalanche"
    if key in {"xdai"}:
        return "gnosis"
    if key in {"zk-sync", "zk-sync-era", "zksync-era"}:
        return "zksync"
    if key in {"polygonzkevm", "polygon-zk-evm"}:
        return "polygon-zkevm"
    return key


def is_supported_evm_chain_key(chain_key: str | None) -> bool:
    """Return True if the chain key represents a supported EVM chain (not Solana)."""
    key = _normalize_chain_key(chain_key or "")
    return key in _EVM_CHAIN_REGISTRY


def resolve_lifi_chain_id(dexscreener_chain_key: str) -> Optional[int]:
    """
    Convert Dexscreener's chain key into a LI.FI numeric chain id.

    Returns:
        chain id if supported, otherwise None.
    """
    key = _normalize_chain_key(dexscreener_chain_key)
    chain = _EVM_CHAIN_REGISTRY.get(key)
    if chain is None:
        log.debug("LI.FI chain resolution failed: unsupported Dexscreener key '%s'", dexscreener_chain_key)
        return None
    return chain.chain_id


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def _http_get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Perform a GET request with sane timeouts and return JSON."""
    timeout = httpx.Timeout(12.0, connect=6.0)
    headers: Dict[str, str] = {}
    # Optional: if you later add an API key
    # headers["x-lifi-api-key"] = settings.LIFI_API_KEY
    with httpx.Client(timeout=timeout, headers=headers) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


# --------------------------------------------------------------------------
# Internal: adaptive amount reducer on high price impact
# --------------------------------------------------------------------------

def _estimate_usd_from_wei(chain_key: str, wei: int) -> Optional[float]:
    """
    Roughly estimate USD notional from a native amount in wei using the live
    native price provider. Returns None if price unavailable.
    """
    try:
        price = get_native_price_usd(chain_key)
        if price is None or price <= 0:
            return None
        # wei -> native
        native = float(wei) / 1e18
        return native * float(price)
    except Exception:
        return None


def _should_reduce_amount_on_404(body: str) -> bool:
    """
    Inspect LI.FI 404 JSON body and detect the "price impact > 10%" filter case.
    """
    try:
        data = json.loads(body or "{}")
        # Typical shape when filtered:
        # { "message":"No available quotes...", "code":1002, "errors":{"filteredOut":[{"reason":"Price impact of ... is higher than the max allowed 10%"}]}}
        errors = (data.get("errors") or {}).get("filteredOut") or []
        for row in errors:
            reason = str(row.get("reason") or "").lower()
            if "price impact" in reason and "max allowed 10%" in reason:
                return True
        return False
    except Exception:
        return False


def _adaptive_get_quote(
        *,
        chain_key: str,
        chain_id: int,
        from_address: str,
        to_token_address: str,
        initial_from_amount_wei: int,
        slippage: float,
        reduce_factor: float = 0.5,
        max_attempts: int = 6,
        min_usd_floor: float = 20.0,
) -> Tuple[Optional[Dict[str, Any]], int]:
    """
    Try to fetch a LI.FI quote, adaptively reducing the amount if LI.FI
    rejects due to high price impact.

    Returns:
        (quote_dict_or_none, final_from_amount_wei)
    """
    url = f"{settings.LIFI_BASE_URL.rstrip('/')}/v1/quote"
    attempt = 1
    from_amount_wei = int(initial_from_amount_wei)

    while attempt <= max_attempts and from_amount_wei > 0:
        params = {
            "fromChain": chain_id,
            "toChain": chain_id,
            "fromToken": EVM_NATIVE_TOKEN_ZERO_ADDRESS,
            "toToken": to_token_address,
            "fromAmount": str(from_amount_wei),
            "fromAddress": from_address,
            "slippage": slippage,
            "allowSwitchChain": "false",
        }

        log.debug(
            "Requesting LI.FI quote (attempt %d/%d): chain=%s(%s) native->%s amountWei=%s slippage=%.4f",
            attempt, max_attempts, chain_key, chain_id, to_token_address, from_amount_wei, slippage
        )

        try:
            data = _http_get_json(url, params)
            log.info(
                "LI.FI quote OK (attempt %d): chain=%s(%s) to=%s tool=%s",
                attempt, chain_key, chain_id, to_token_address,
                (data.get("tool") or data.get("estimate", {}).get("tool") or "n/a"),
            )
            return data, from_amount_wei

        except httpx.HTTPStatusError as exc:
            # Only reduce if it's the "price impact > 10%" case
            body = exc.response.text or ""
            if exc.response.status_code == 404 and _should_reduce_amount_on_404(body):
                # Optionally stop if USD would be too small
                est_usd = _estimate_usd_from_wei(chain_key, from_amount_wei) or -1.0
                if est_usd >= 0 and est_usd < min_usd_floor:
                    log.warning(
                        "LI.FI: amount too small after reductions (≈$%.2f < $%.2f). Giving up.",
                        est_usd, min_usd_floor
                    )
                    return None, from_amount_wei

                log.warning(
                    "LI.FI: high price impact at attempt %d, reducing amount (was wei=%s, est≈$%.2f). "
                    "Reason: %s",
                    attempt, from_amount_wei, est_usd if est_usd >= 0 else float("nan"), body[:180].replace("\n", " ")
                )
                from_amount_wei = max(1, math.floor(from_amount_wei * float(reduce_factor)))
                attempt += 1
                continue

            # Other errors: do not loop endlessly; propagate.
            log.warning("LI.FI GET %s failed (%s): %s", url, exc.response.status_code, body)
            raise

    # Exhausted attempts
    return None, from_amount_wei


# --------------------------------------------------------------------------
# Quotes (public)
# --------------------------------------------------------------------------

def build_native_to_token_quote(
        *,
        chain_key: str,
        from_address: str,
        to_token_address: str,
        from_amount_wei: int,
        slippage: float = 0.03,
        # Adaptive controls (optional; tuned for microcaps)
        enable_adaptive_reduction: bool = True,
        reduce_factor: float = 0.5,
        max_attempts: int = 6,
        min_usd_floor: float = 20.0,
) -> Dict[str, Any]:
    """
    Build a LI.FI single-step quote to swap native coin -> ERC20 on the SAME chain.
    If LI.FI rejects due to high price impact, we reduce the amount and retry.

    Args:
        chain_key: Dexscreener chain key (e.g. "ethereum", "bsc", "polygon", "base"…).
        from_address: EVM wallet address that will execute the swap.
        to_token_address: ERC20 token address on the same chain.
        from_amount_wei: Native amount to swap, in wei.
        slippage: Allowed slippage (e.g. 0.03 = 3%).
        enable_adaptive_reduction: Turn on auto-reduction when price impact is too high.
        reduce_factor: Multiply amount by this factor on each reduction (0.5 halves the size).
        max_attempts: Max attempts including the first one.
        min_usd_floor: Stop reducing if the estimated USD notional would drop below this.

    Returns:
        The LI.FI quote response (dict) that contains a transactionRequest.

    Raises:
        ValueError if the chain is unsupported or inputs are invalid, or if
        all attempts fail to produce a quote.
    """
    if not from_address or not to_token_address:
        raise ValueError("from_address and to_token_address must be provided.")
    if from_amount_wei <= 0:
        raise ValueError("from_amount_wei must be > 0.")

    chain_id = resolve_lifi_chain_id(chain_key)
    if chain_id is None:
        raise ValueError(f"Unsupported EVM chain for LI.FI: '{chain_key}'")

    if not enable_adaptive_reduction:
        # Single attempt (original behavior).
        url = f"{settings.LIFI_BASE_URL.rstrip('/')}/v1/quote"
        params = {
            "fromChain": chain_id,
            "toChain": chain_id,
            "fromToken": EVM_NATIVE_TOKEN_ZERO_ADDRESS,
            "toToken": to_token_address,
            "fromAmount": str(from_amount_wei),
            "fromAddress": from_address,
            "slippage": slippage,
            "allowSwitchChain": "false",
        }
        log.debug(
            "Requesting LI.FI quote: chain=%s(%s) native->%s amountWei=%s slippage=%.4f",
            chain_key, chain_id, to_token_address, from_amount_wei, slippage
        )
        data = _http_get_json(url, params)
        log.info(
            "LI.FI quote OK: chain=%s(%s) to=%s tool=%s",
            chain_key, chain_id,
            to_token_address,
            (data.get("tool") or data.get("estimate", {}).get("tool") or "n/a"),
        )
        return data

    # Adaptive path: reduce amount on 404 high price impact
    data, final_wei = _adaptive_get_quote(
        chain_key=chain_key,
        chain_id=chain_id,
        from_address=from_address,
        to_token_address=to_token_address,
        initial_from_amount_wei=from_amount_wei,
        slippage=slippage,
        reduce_factor=reduce_factor,
        max_attempts=max_attempts,
        min_usd_floor=min_usd_floor,
    )
    if data is None:
        raise ValueError(
            f"LI.FI could not provide a quote after {max_attempts} attempts "
            f"(final wei={final_wei})."
        )
    return data

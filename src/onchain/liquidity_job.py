# src/onchain/liquidity_job.py
from typing import Optional, Tuple
from web3 import Web3
from ..config import settings
from ..logger import get_logger

log = get_logger(__name__)

UNISWAP_V2_PAIR_ABI = [
    {"name": "getReserves", "outputs": [{"type":"uint112","name":"_reserve0"},{"type":"uint112","name":"_reserve1"},{"type":"uint32","name":"_blockTimestampLast"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token0", "outputs": [{"type":"address"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "token1", "outputs": [{"type":"address"}], "inputs": [], "stateMutability": "view", "type": "function"},
]

_prev_liq_eth: dict[str, float] = {}

def _human_eth(wei: int) -> float:
    try:
        return float(Web3.from_wei(wei, "ether"))
    except Exception:
        return 0.0

def fetch_weth_liquidity(w3: Web3, pair_addr: str) -> Optional[Tuple[float, float, float]]:
    """
    Retourne (liq_weth_eth, reserve0_eth, reserve1_eth)
    """
    try:
        pair = w3.eth.contract(address=Web3.to_checksum_address(pair_addr), abi=UNISWAP_V2_PAIR_ABI)
        t0 = pair.functions.token0().call()
        t1 = pair.functions.token1().call()
        r0, r1, _ = pair.functions.getReserves().call()

        r0_eth = _human_eth(r0) if t0.lower() == settings.WETH_ADDRESS.lower() else 0.0
        r1_eth = _human_eth(r1) if t1.lower() == settings.WETH_ADDRESS.lower() else 0.0
        liq = r0_eth + r1_eth
        return liq, r0_eth, r1_eth
    except Exception as e:
        log.debug("fetch_weth_liquidity error pair=%s: %s", pair_addr, e)
        return None

def probe_pair(w3: Web3, pair_addr: str):
    res = fetch_weth_liquidity(w3, pair_addr)
    if not res:
        log.debug("[ONCHAIN] pair %s: no reserves yet", pair_addr)
        return
    liq, e0, e1 = res
    prev = _prev_liq_eth.get(pair_addr)
    if prev is None:
        log.debug("[ONCHAIN] pair %s: WETH_liq=%.4f (token0=%.4f, token1=%.4f) — first sample",
                  pair_addr, liq, e0, e1)
    else:
        delta = liq - prev
        dpct = (delta / prev * 100.0) if prev > 0 else 0.0
        log.debug("[ONCHAIN] pair %s: WETH_liq=%.4f Δ=%.4f (%.2f%%) (token0=%.4f, token1=%.4f)",
                  pair_addr, liq, delta, dpct, e0, e1)

    _prev_liq_eth[pair_addr] = liq

    if liq >= settings.MIN_LIQ_ETH:
        log.info("[ONCHAIN][OK] pair %s: WETH_liq=%.4f ≥ %.2f", pair_addr, liq, settings.MIN_LIQ_ETH)
    else:
        log.debug("[ONCHAIN][LOW] pair %s: WETH_liq=%.4f < %.2f", pair_addr, liq, settings.MIN_LIQ_ETH)

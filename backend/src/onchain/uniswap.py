# src/onchain/uniswap.py
from web3 import Web3
from ..config import settings
from ..logger import get_logger

log = get_logger(__name__)

# ABIs minimales
FACTORY_ABI = [
    {"name":"getPair","outputs":[{"type":"address","name":""}],
     "inputs":[{"type":"address","name":"tokenA"},{"type":"address","name":"tokenB"}],
     "stateMutability":"view","type":"function"},
]
PAIR_ABI = [
    {"name":"getReserves","outputs":[{"type":"uint112","name":"_reserve0"},{"type":"uint112","name":"_reserve1"},{"type":"uint32","name":"_blockTimestampLast"}],
     "inputs":[],"stateMutability":"view","type":"function"},
    {"name":"token0","outputs":[{"type":"address","name":""}],"inputs":[],"stateMutability":"view","type":"function"},
    {"name":"token1","outputs":[{"type":"address","name":""}],"inputs":[],"stateMutability":"view","type":"function"},
]

def _cs(addr: str) -> str:
    return Web3.to_checksum_address(addr)

def get_pair(w3: Web3, token_addr: str,
             factory_addr: str | None = None,
             weth_addr: str | None = None) -> str | None:
    """Retourne l’adresse de la pair UniswapV2 (token/WETH) ou None."""
    try:
        factory = _cs(factory_addr or settings.UNISWAP_FACTORY_ADDRESS)
        weth = _cs(weth_addr or settings.WETH_ADDRESS)
        tok = _cs(token_addr)
        c = w3.eth.contract(address=factory, abi=FACTORY_ABI)
        pair = c.functions.getPair(tok, weth).call()
        if int(pair, 16) == 0:
            log.debug("[PAIR] not found token=%s", tok)
            return None
        log.debug("[PAIR] token=%s → pair=%s", tok, pair)
        return pair
    except Exception as e:
        log.debug("[PAIR][ERR] token=%s error=%s", token_addr, e)
        return None

def reserves(w3: Web3, pair_addr: str, weth_addr: str | None = None) -> float:
    """
    Retourne la liquidité WETH en ETH (float).
    0.0 si échec.
    """
    try:
        pair = _cs(pair_addr)
        weth = _cs(weth_addr or settings.WETH_ADDRESS)
        p = w3.eth.contract(address=pair, abi=PAIR_ABI)
        r0, r1, _t = p.functions.getReserves().call()
        t0 = p.functions.token0().call()
        t1 = p.functions.token1().call()
        if t0.lower() == weth.lower():
            liq = r0 / 1e18
        elif t1.lower() == weth.lower():
            liq = r1 / 1e18
        else:
            # pas de WETH sur la paire (peu probable ici)
            liq = 0.0
        log.debug("[RESERVES] pair=%s token0=%s token1=%s r0=%s r1=%s → WETH_liq=%.6f",
                  pair, t0, t1, r0, r1, liq)
        return liq
    except Exception as e:
        log.debug("[RESERVES][ERR] pair=%s error=%s", pair_addr, e)
        return 0.0

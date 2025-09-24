# chart_gate.py
import math, requests
from statistics import mean

def _ema(vals, n):
    k = 2/(n+1)
    ema = None
    out = []
    for v in vals:
        ema = v if ema is None else (v*k + ema*(1-k))
        out.append(ema)
    return out

def _rsi(closes, n=14):
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < n: return None
    avg_gain = mean(gains[-n:])
    avg_loss = mean(losses[-n:])
    if avg_loss == 0: return 100.0
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def _atr(highs, lows, closes, n=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i]-lows[i],
            abs(highs[i]-closes[i-1]),
            abs(lows[i]-closes[i-1]),
        )
        trs.append(tr)
    return mean(trs[-n:]) if len(trs) >= n else None

def _vwap(closes, vols):
    # VWAP simple sur toute la fenêtre
    num = sum(c*v for c, v in zip(closes, vols))
    den = sum(vols) or 1.0
    return num/den

def _best_pair_eth(token_addr):
    js = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}").json()
    pairs = [p for p in js.get("pairs", []) if p.get("chainId") == "ethereum"]
    if not pairs: return None
    # tri par liquidité USD
    pairs.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0.0), reverse=True)
    return pairs[0]

def _fetch_candles_1m(pair_address, limit=120):
    url = f"https://api.dexscreener.com/latest/dex/candles/ethereum/1m/{pair_address}?limit={limit}"
    js = requests.get(url, timeout=10).json()
    return js.get("candles") or []

def chart_ok(token_addr) -> bool:
    pair = _best_pair_eth(token_addr)
    if not pair: return False
    candles = _fetch_candles_1m(pair["pairAddress"], limit=120)
    if len(candles) < 40:  # un peu d'historique
        return False

    closes = [float(c["close"]) for c in candles]
    highs  = [float(c["high"])  for c in candles]
    lows   = [float(c["low"])   for c in candles]
    # volume en USD si dispo, sinon fallback à 1
    vols   = [float((c.get("volume") or {}).get("usd") or 1.0) for c in candles]

    ema5  = _ema(closes, 5)[-1]
    ema20 = _ema(closes, 20)[-1]
    rsi14 = _rsi(closes, 14)
    atr14 = _atr(highs, lows, closes, 14)
    vwap30 = _vwap(closes[-30:], vols[-30:])
    c = closes[-1]

    # Règles
    if not (ema5 and ema20 and atr14 and rsi14): return False
    if ema5 <= ema20: return False
    if c <= vwap30: return False
    if (highs[-1] - lows[-1]) > 2.0 * atr14: return False
    if rsi14 < 55 or rsi14 > 85: return False
    if vols[-1] < 1.5 * (mean(vols[-20:]) or 1.0): return False

    # Cooldown après spike: exige 2 clôtures > EMA5
    ema5_series = _ema(closes, 5)
    if not (closes[-1] > ema5_series[-1] and closes[-2] > ema5_series[-2]):
        return False

    return True

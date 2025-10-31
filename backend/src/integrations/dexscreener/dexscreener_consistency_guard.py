from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Deque, Dict, Optional

import logging

from src.core.utils.date_utils import timezone_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PairIdentity:
    """Stable identity for a traded pair (pool-aware)."""
    chain: str
    token_address: str
    pair_address: str

    def key(self) -> str:
        return f"{self.chain}:{self.pair_address or self.token_address}".lower()


@dataclass(frozen=True)
class Observation:
    """Minimal observation for consistency checks."""
    as_of: Optional[datetime]
    price_usd: Optional[float]
    liquidity_usd: Optional[float]
    fully_diluted_valuation_usd: Optional[float]
    market_cap_usd: Optional[float]
    buys_5m: Optional[int]
    sells_5m: Optional[int]


class ConsistencyVerdict(Enum):
    OK = "OK"
    REQUIRES_MANUAL_INTERVENTION = "REQUIRES_MANUAL_INTERVENTION"


@dataclass
class _State:
    recent_fingerprints: Deque[str]
    last_price_usd: Optional[float]


class DexConsistencyGuard:
    """
    Detects provider inconsistency (Dexscreener A↔B dataset alternation or multi-field jumps).
    This guard is intentionally tolerant to missing fields: it can operate with price only.
    """

    def __init__(
            self,
            *,
            window_size: int,
            alternation_min_cycles: int,
            price_jump_factor: float,
            fields_mismatch_min: int,
            staleness_horizon: timedelta,
    ) -> None:
        self._window_size = max(2, int(window_size))
        self._alternation_min_cycles = max(1, int(alternation_min_cycles))
        self._price_jump_factor = max(1.0, float(price_jump_factor))
        self._fields_mismatch_min = max(1, int(fields_mismatch_min))
        self._staleness_horizon = staleness_horizon
        self._states: Dict[str, _State] = {}

    @staticmethod
    def _bucket(value: Optional[float], *, granularity: float) -> str:
        if value is None:
            return "NA"
        if value <= 0:
            return "Z"
        # logarithmic-ish bucketing to resist small fluctuations
        return f"{round(value / max(granularity, 1e-12))}"

    def _fingerprint(self, o: Observation) -> str:
        """
        Build a coarse fingerprint intended to remain stable for a single truthful dataset,
        but differ when Dexscreener alternates across pools.
        """
        p = self._bucket(o.price_usd, granularity=1e-6)
        l = self._bucket(o.liquidity_usd, granularity=10.0)
        f = self._bucket(o.fully_diluted_valuation_usd, granularity=1000.0)
        m = self._bucket(o.market_cap_usd, granularity=1000.0)
        b = "NA" if o.buys_5m is None else str(o.buys_5m // 5)
        s = "NA" if o.sells_5m is None else str(o.sells_5m // 5)
        return f"p={p}|l={l}|fdv={f}|mcap={m}|b5={b}|s5={s}"

    @staticmethod
    def _alternates(seq: Deque[str], min_cycles: int) -> bool:
        """
        True when the tail of 'seq' looks like A,B,A,B,... for at least 'min_cycles'.
        """
        needed = 2 * min_cycles
        if len(seq) < needed:
            return False
        tail = list(seq)[-needed:]
        unique = list(dict.fromkeys(tail))
        if len(unique) != 2:
            return False
        a, b = unique[0], unique[1]
        for idx, fp in enumerate(tail):
            if fp != (a if idx % 2 == 0 else b):
                return False
        return True

    @staticmethod
    def _ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None or b == 0.0:
            return None
        return a / b if a > 0.0 and b > 0.0 else None

    def observe(self, pair: PairIdentity, obs: Observation) -> ConsistencyVerdict:
        """
        Ingest one observation and decide whether the feed is inconsistent.

        Tripwires (in order):
          1) Immediate: price jump ≥ price_jump_factor vs last seen → STALE (prevents a first flip autosell).
          2) Alternation: fingerprint ABAB... for 'alternation_min_cycles'.
        """
        key = pair.key()
        state = self._states.get(key)
        if state is None:
            state = _State(recent_fingerprints=deque(maxlen=self._window_size), last_price_usd=None)
            self._states[key] = state

        # Staleness: ignore acting on very old observations
        if obs.as_of is not None:
            try:
                if (timezone_now() - obs.as_of) > self._staleness_horizon:
                    logger.debug("[DEX][CONSISTENCY][STALE] key=%s obs too old", key)
                    # Record fingerprint but do not act
                    state.recent_fingerprints.append(self._fingerprint(obs))
                    state.last_price_usd = obs.price_usd
                    return ConsistencyVerdict.OK
            except Exception:
                # If clock skew / invalid time, continue safely
                pass

        # (1) Tripwire: immediate multi-order jump on price alone
        if state.last_price_usd is not None:
            ratio = self._ratio(obs.price_usd, state.last_price_usd)
            if ratio is not None and (ratio >= self._price_jump_factor or ratio <= 1.0 / self._price_jump_factor):
                logger.info(
                    "[DEX][CONSISTENCY][TRIPWIRE] key=%s price jump=%.6f → requires manual intervention",
                    key, ratio
                )
                state.recent_fingerprints.append(self._fingerprint(obs))
                state.last_price_usd = obs.price_usd
                return ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION

        # Record and test alternation
        fp = self._fingerprint(obs)
        state.recent_fingerprints.append(fp)
        state.last_price_usd = obs.price_usd

        if self._alternates(state.recent_fingerprints, self._alternation_min_cycles):
            logger.info("[DEX][CONSISTENCY][ALTERNATION] key=%s detected AB pattern", key)
            return ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION

        return ConsistencyVerdict.OK

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Deque, Dict, Optional

from src.core.utils.date_utils import timezone_now
from src.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PairIdentity:
    """
    Stable identity for a traded pair (pool-aware).

    The `key()` is used to partition internal state by chain and pool (pair address when available).
    """
    chain: str
    token_address: str
    pair_address: str

    def key(self) -> str:
        strict_pair_or_token = self.pair_address if self.pair_address else self.token_address
        return f"{self.chain}:{strict_pair_or_token}".lower()


@dataclass(frozen=True)
class WindowActivity:
    """
    Activity snapshot for a time window.

    Only `buys` and `sells` are modeled here as they are the most stable cross-sources signals.
    Additional fields can be added later without changing the guard's logic.
    """
    buys: Optional[int]
    sells: Optional[int]

    def total_transactions(self) -> Optional[int]:
        if self.buys is None or self.sells is None:
            return None
        return int(self.buys + self.sells)


@dataclass(frozen=True)
class Observation:
    """
    Minimal observation for **consistency** checks ONLY.

    IMPORTANT: This class is intentionally narrow in scope. It focuses on
    multi-field jump detection and ABAB alternation caused by source pool
    switching. It does **not** perform semantic contradictions checks
    (e.g., FDV vs Market Cap) — those belong to gates at selection time.
    """
    as_of: Optional[datetime]
    liquidity_usd: Optional[float]
    fully_diluted_valuation_usd: Optional[float]
    market_cap_usd: Optional[float]
    window_5m: Optional[WindowActivity]
    window_1h: Optional[WindowActivity]
    window_6h: Optional[WindowActivity]
    window_24h: Optional[WindowActivity]


class ConsistencyVerdict(Enum):
    OK = "OK"
    REQUIRES_MANUAL_INTERVENTION = "REQUIRES_MANUAL_INTERVENTION"


@dataclass
class _State:
    recent_fingerprints: Deque[str]
    last_liquidity_usd: Optional[float]
    last_fully_diluted_valuation_usd: Optional[float]
    last_market_cap_usd: Optional[float]
    last_txns_5m: Optional[int]
    last_txns_1h: Optional[int]
    last_txns_6h: Optional[int]
    last_txns_24h: Optional[int]


class DexConsistencyGuard:
    """
    Detect provider **inconsistency** and **multi-field abnormal jumps** on:

      - liquidity_usd
      - fully_diluted_valuation_usd
      - market_cap_usd
      - windowed transactions: 5m / 1h / 6h / 24h

    This guard is designed to protect the runtime (including live positions)
    against the well-known Dexscreener ABAB alternation bug and sudden
    cross-field discontinuities. It deliberately **does not** run semantic
    contradictions; push those to selection gates.
    """

    def __init__(
            self,
            *,
            window_size: int,
            alternation_min_cycles: int,
            jump_factor: float,
            fields_mismatch_min: int,
            staleness_horizon: timedelta,
    ) -> None:
        self._window_size = max(2, int(window_size))
        self._alternation_min_cycles = max(1, int(alternation_min_cycles))
        self._jump_factor = max(1.0, float(jump_factor))
        self._fields_mismatch_min = max(1, int(fields_mismatch_min))
        self._staleness_horizon = staleness_horizon
        self._states: Dict[str, _State] = {}

    # ---------- helpers ---------- #

    @staticmethod
    def _bucket_float(value: Optional[float], *, granularity: float) -> str:
        if value is None:
            return "NA"
        if value <= 0.0:
            return "Z"
        safe = max(granularity, 1e-12)
        return f"{round(value / safe)}"

    @staticmethod
    def _bucket_int(value: Optional[int], *, divisor: int) -> str:
        if value is None:
            return "NA"
        if value <= 0:
            return "Z"
        safe = max(divisor, 1)
        return f"{value // safe}"

    @staticmethod
    def _total_txns(w: Optional[WindowActivity]) -> Optional[int]:
        return w.total_transactions() if w else None

    def _fingerprint(self, o: Observation) -> str:
        """
        Build a coarse fingerprint that is resilient to small numeric noise, yet
        switches when the upstream alternates pools.
        """
        l = self._bucket_float(o.liquidity_usd, granularity=10.0)
        f = self._bucket_float(o.fully_diluted_valuation_usd, granularity=1000.0)
        m = self._bucket_float(o.market_cap_usd, granularity=1000.0)

        tx5 = self._bucket_int(self._total_txns(o.window_5m), divisor=5)
        tx1 = self._bucket_int(self._total_txns(o.window_1h), divisor=10)
        tx6 = self._bucket_int(self._total_txns(o.window_6h), divisor=50)
        tx24 = self._bucket_int(self._total_txns(o.window_24h), divisor=200)

        return f"l={l}|fdv={f}|mcap={m}|t5={tx5}|t1={tx1}|t6={tx6}|t24={tx24}"

    @staticmethod
    def _alternates(seq: Deque[str], min_cycles: int) -> bool:
        """
        True when the tail of 'seq' looks like A,B,A,B,... for at least 'min_cycles'.
        """
        needed = 2 * min_cycles
        if len(seq) < needed:
            return False
        tail = list(seq)[-needed:]
        a, b = tail[0], tail[1]
        if a == b:
            return False
        for idx, fp in enumerate(tail):
            if fp != (a if idx % 2 == 0 else b):
                return False
        return True

    @staticmethod
    def _ratio(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or previous is None:
            return None
        if previous == 0.0:
            return None
        if current <= 0.0 or previous <= 0.0:
            return None
        return current / previous

    @staticmethod
    def _jumped(current: Optional[float], previous: Optional[float], factor: float) -> bool:
        """
        Decide if a value has jumped abnormally between two observations.
        - If either side is None → not enough info.
        - 0 → positive or positive → 0 is considered a jump.
        - Otherwise, compare ratio to the factor threshold.
        """
        if current is None or previous is None:
            return False
        if current == 0.0 and previous == 0.0:
            return False
        if current == 0.0 or previous == 0.0:
            return True
        if current < 0.0 or previous < 0.0:
            return True
        ratio = current / previous
        return ratio >= factor or ratio <= 1.0 / factor

    @staticmethod
    def _now_is_stale(as_of: Optional[datetime], horizon: timedelta) -> bool:
        if as_of is None:
            return False
        try:
            return (timezone_now() - as_of) > horizon
        except Exception:
            return False

    # ---------- public API ---------- #

    def observe(self, pair: PairIdentity, obs: Observation) -> ConsistencyVerdict:
        """
        Ingest one observation and decide whether the feed is inconsistent.

        Tripwires (in order):
          1) Staleness guard: ignore acting on excessively old observations.
          2) Multi-field jumps: if >= N fields jump simultaneously by factor F, flag.
          3) Alternation: fingerprint ABAB... for 'alternation_min_cycles'.

        Returns:
            ConsistencyVerdict
        """
        key = pair.key()
        state = self._states.get(key)
        if state is None:
            state = _State(
                recent_fingerprints=deque(maxlen=self._window_size),
                last_liquidity_usd=None,
                last_fully_diluted_valuation_usd=None,
                last_market_cap_usd=None,
                last_txns_5m=None,
                last_txns_1h=None,
                last_txns_6h=None,
                last_txns_24h=None,
            )
            self._states[key] = state

        # (1) If the event is too old, just record the fingerprint and update state silently.
        if self._now_is_stale(obs.as_of, self._staleness_horizon):
            logger.debug("[DEX][CONSISTENCY][STALE] key=%s observation too old, skipping actions", key)
            fp = self._fingerprint(obs)
            state.recent_fingerprints.append(fp)
            state.last_liquidity_usd = obs.liquidity_usd
            state.last_fully_diluted_valuation_usd = obs.fully_diluted_valuation_usd
            state.last_market_cap_usd = obs.market_cap_usd
            state.last_txns_5m = self._total_txns(obs.window_5m)
            state.last_txns_1h = self._total_txns(obs.window_1h)
            state.last_txns_6h = self._total_txns(obs.window_6h)
            state.last_txns_24h = self._total_txns(obs.window_24h)
            return ConsistencyVerdict.OK

        # (2) Multi-field synchronous jumps across the required set
        jump_fields = 0
        ratios_log: list[str] = []

        def test_float(name: str, current: Optional[float], previous: Optional[float]) -> None:
            nonlocal jump_fields
            if self._jumped(current, previous, self._jump_factor):
                jump_fields += 1
                if current is not None and previous is not None and previous > 0.0 and current > 0.0:
                    ratios_log.append(f"{name}={current/previous:.4f}")
                else:
                    ratios_log.append(f"{name}=EDGE")

        def test_int(name: str, current: Optional[int], previous: Optional[int]) -> None:
            nonlocal jump_fields
            curf = float(current) if current is not None else None
            prevf = float(previous) if previous is not None else None
            if self._jumped(curf, prevf, self._jump_factor):
                jump_fields += 1
                if curf is not None and prevf is not None and prevf > 0.0 and curf > 0.0:
                    ratios_log.append(f"{name}={curf/prevf:.4f}")
                else:
                    ratios_log.append(f"{name}=EDGE")

        test_float("liquidity", obs.liquidity_usd, state.last_liquidity_usd)
        test_float("fdv", obs.fully_diluted_valuation_usd, state.last_fully_diluted_valuation_usd)
        test_float("mcap", obs.market_cap_usd, state.last_market_cap_usd)
        test_int("tx5m", self._total_txns(obs.window_5m), state.last_txns_5m)
        test_int("tx1h", self._total_txns(obs.window_1h), state.last_txns_1h)
        test_int("tx6h", self._total_txns(obs.window_6h), state.last_txns_6h)
        test_int("tx24h", self._total_txns(obs.window_24h), state.last_txns_24h)

        if jump_fields >= self._fields_mismatch_min:
            logger.info(
                "[DEX][CONSISTENCY][MULTI_JUMP] key=%s jump_fields=%d/%d ratios=[%s] → [REQUIRES_MANUAL_INTERVENTION]",
                key,
                jump_fields,
                7,
                ", ".join(ratios_log),
            )
            fp = self._fingerprint(obs)
            state.recent_fingerprints.append(fp)
            state.last_liquidity_usd = obs.liquidity_usd
            state.last_fully_diluted_valuation_usd = obs.fully_diluted_valuation_usd
            state.last_market_cap_usd = obs.market_cap_usd
            state.last_txns_5m = self._total_txns(obs.window_5m)
            state.last_txns_1h = self._total_txns(obs.window_1h)
            state.last_txns_6h = self._total_txns(obs.window_6h)
            state.last_txns_24h = self._total_txns(obs.window_24h)
            return ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION

        # (3) Record fingerprint and test alternation last
        fp = self._fingerprint(obs)
        state.recent_fingerprints.append(fp)
        state.last_liquidity_usd = obs.liquidity_usd
        state.last_fully_diluted_valuation_usd = obs.fully_diluted_valuation_usd
        state.last_market_cap_usd = obs.market_cap_usd
        state.last_txns_5m = self._total_txns(obs.window_5m)
        state.last_txns_1h = self._total_txns(obs.window_1h)
        state.last_txns_6h = self._total_txns(obs.window_6h)
        state.last_txns_24h = self._total_txns(obs.window_24h)

        if self._alternates(state.recent_fingerprints, self._alternation_min_cycles):
            logger.info("[DEX][CONSISTENCY][ALTERNATION] key=%s detected AB pattern", key)
            return ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION

        return ConsistencyVerdict.OK

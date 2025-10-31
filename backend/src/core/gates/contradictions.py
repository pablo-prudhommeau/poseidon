from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.core.structures.structures import Candidate
from src.integrations.dexscreener.dexscreener_structures import TokenPrice
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class GateVerdict:
    """
    Verdict returned by the contradictions gate.
    - is_ok: True means the candidate passes all checks.
    - reasons: list of short machine-readable reasons for failures.
    """
    is_ok: bool
    reasons: List[str]


class DexscreenerContradictionsGate:
    """
    Semantic sanity checks that must happen **pre-trade** (selection phase), not at runtime:
      - FDV must be >= Market Cap
      - Liquidity should not exceed Market Cap (extreme cases are suspicious)
      - Volume/Transactions conflict on 24h (volume>0 with 0 txns, or txns>0 with 0 volume)
      - Transactions monotonicity across windows: 5m ≤ 1h ≤ 6h ≤ 24h

    Notes:
      - This gate uses only a single snapshot; it does NOT detect jumps over time.
      - Missing fields are tolerated: a check is applied only if all required inputs are present.
    """

    @staticmethod
    def _total_transactions(buys: Optional[int], sells: Optional[int]) -> Optional[int]:
        if buys is None or sells is None:
            return None
        return int(buys + sells)

    @staticmethod
    def _txns_from_price(price: TokenPrice, window: str) -> Optional[int]:
        """
        Extract total transactions for a given window from TokenPrice.txns.
        Expected windows: 'm5', 'h1', 'h6', 'h24'.
        """
        if price.txns is None:
            return None
        if window == "m5" and price.txns.m5:
            return DexscreenerContradictionsGate._total_transactions(price.txns.m5.buys, price.txns.m5.sells)
        if window == "h1" and price.txns.h1:
            return DexscreenerContradictionsGate._total_transactions(price.txns.h1.buys, price.txns.h1.sells)
        if window == "h6" and price.txns.h6:
            return DexscreenerContradictionsGate._total_transactions(price.txns.h6.buys, price.txns.h6.sells)
        if window == "h24" and price.txns.h24:
            return DexscreenerContradictionsGate._total_transactions(price.txns.h24.buys, price.txns.h24.sells)
        return None

    @staticmethod
    def _non_decreasing(sequence: List[Optional[int]]) -> bool:
        """
        Validate non-decreasing order, ignoring None gaps.
        """
        last: Optional[int] = None
        for value in sequence:
            if value is None:
                continue
            if last is not None and value < last:
                return False
            last = value
        return True

    def evaluate(self, candidate: Candidate, token_price: Optional[TokenPrice]) -> GateVerdict:
        """
        Run contradictions checks against candidate+price snapshot.
        """
        reasons: List[str] = []

        if token_price is not None:
            # FDV must be >= Market Cap (allow a tiny tolerance, 5%)
            if token_price.fdvUsd is not None and token_price.marketCapUsd is not None:
                if token_price.marketCapUsd > token_price.fdvUsd * 1.05:
                    reasons.append("FDV_LT_MARKETCAP")

            # Liquidity should not exceed Market Cap (highly unusual)
            if token_price.liquidityUsd is not None and token_price.marketCapUsd is not None:
                if token_price.liquidityUsd > token_price.marketCapUsd:
                    reasons.append("LIQUIDITY_GT_MARKETCAP")

            # 24h Volume ↔ 24h Transactions conflict
            vol24_usd: Optional[float] = token_price.volumeH24Usd
            tx24: Optional[int] = self._txns_from_price(token_price, "h24")
            if vol24_usd is not None and tx24 is not None:
                if (vol24_usd > 0.0 and tx24 == 0) or (vol24_usd == 0.0 and tx24 > 0):
                    reasons.append("VOLUME_TXNS_CONFLICT")

            # Transactions monotonicity: 5m ≤ 1h ≤ 6h ≤ 24h (when present)
            tx5 = self._txns_from_price(token_price, "m5")
            tx1 = self._txns_from_price(token_price, "h1")
            tx6 = self._txns_from_price(token_price, "h6")
            tx24 = self._txns_from_price(token_price, "h24")
            if not self._non_decreasing([tx5, tx1, tx6, tx24]):
                reasons.append("TXNS_NON_MONOTONIC")

        return GateVerdict(is_ok=(len(reasons) == 0), reasons=reasons)

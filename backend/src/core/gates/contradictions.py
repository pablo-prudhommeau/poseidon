from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.core.structures.structures import Candidate
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class GateVerdict:
    is_ok: bool
    reasons: List[str]


class DexscreenerContradictionsGate:
    @staticmethod
    def _total_transactions(buys: Optional[int], sells: Optional[int]) -> Optional[int]:
        if buys is None or sells is None:
            return None
        return int(buys + sells)

    @staticmethod
    def _txns_from_token_information(token_information: DexscreenerTokenInformation, window: str) -> Optional[int]:
        if token_information.txns is None:
            return None
        if window == "m5" and token_information.txns.m5:
            return DexscreenerContradictionsGate._total_transactions(token_information.txns.m5.buys, token_information.txns.m5.sells)
        if window == "h1" and token_information.txns.h1:
            return DexscreenerContradictionsGate._total_transactions(token_information.txns.h1.buys, token_information.txns.h1.sells)
        if window == "h6" and token_information.txns.h6:
            return DexscreenerContradictionsGate._total_transactions(token_information.txns.h6.buys, token_information.txns.h6.sells)
        if window == "h24" and token_information.txns.h24:
            return DexscreenerContradictionsGate._total_transactions(token_information.txns.h24.buys, token_information.txns.h24.sells)
        return None

    @staticmethod
    def _non_decreasing(sequence: List[Optional[int]]) -> bool:
        last: Optional[int] = None
        for value in sequence:
            if value is None:
                continue
            if last is not None and value < last:
                return False
            last = value
        return True

    def evaluate(self, candidate: Candidate, token_information: Optional[DexscreenerTokenInformation]) -> GateVerdict:
        reasons: List[str] = []

        if token_information is not None:
            if token_information.fully_diluted_valuation is not None and token_information.market_cap is not None:
                if token_information.market_cap > token_information.fully_diluted_valuation * 1.05:
                    reasons.append("FDV_LT_MARKETCAP")

            if token_information.liquidity is not None and token_information.market_cap is not None:
                if token_information.liquidity.usd > token_information.market_cap:
                    reasons.append("LIQUIDITY_GT_MARKETCAP")

            vol24_usd: Optional[float] = token_information.volume.h24
            tx24: Optional[int] = self._txns_from_token_information(token_information, "h24")
            if vol24_usd is not None and tx24 is not None:
                if (vol24_usd > 0.0 and tx24 == 0) or (vol24_usd == 0.0 and tx24 > 0):
                    reasons.append("VOLUME_TXNS_CONFLICT")

            tx5 = self._txns_from_token_information(token_information, "m5")
            tx1 = self._txns_from_token_information(token_information, "h1")
            tx6 = self._txns_from_token_information(token_information, "h6")
            tx24 = self._txns_from_token_information(token_information, "h24")
            if not self._non_decreasing([tx5, tx1, tx6, tx24]):
                reasons.append("TXNS_NON_MONOTONIC")

        return GateVerdict(is_ok=(len(reasons) == 0), reasons=reasons)

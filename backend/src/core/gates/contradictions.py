from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.core.structures.structures import Candidate
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger

logger = get_logger(__name__)


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
    def _transactions_from_token_information(token_information: DexscreenerTokenInformation, window: str) -> Optional[int]:
        if token_information.transactions is None:
            return None
        if window == "m5" and token_information.transactions.m5:
            return DexscreenerContradictionsGate._total_transactions(token_information.transactions.m5.buys, token_information.transactions.m5.sells)
        if window == "h1" and token_information.transactions.h1:
            return DexscreenerContradictionsGate._total_transactions(token_information.transactions.h1.buys, token_information.transactions.h1.sells)
        if window == "h6" and token_information.transactions.h6:
            return DexscreenerContradictionsGate._total_transactions(token_information.transactions.h6.buys, token_information.transactions.h6.sells)
        if window == "h24" and token_information.transactions.h24:
            return DexscreenerContradictionsGate._total_transactions(token_information.transactions.h24.buys, token_information.transactions.h24.sells)
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

            volume_24h_usd: Optional[float] = token_information.volume.h24 if token_information.volume else None
            transactions_24h = self._transactions_from_token_information(token_information, "h24")
            if volume_24h_usd is not None and transactions_24h is not None:
                if (volume_24h_usd > 0.0 and transactions_24h == 0) or (volume_24h_usd == 0.0 and transactions_24h > 0):
                    reasons.append("VOLUME_TXNS_CONFLICT")

            transactions_5m = self._transactions_from_token_information(token_information, "m5")
            transactions_1h = self._transactions_from_token_information(token_information, "h1")
            transactions_6h = self._transactions_from_token_information(token_information, "h6")
            transactions_24h = self._transactions_from_token_information(token_information, "h24")
            if not self._non_decreasing([transactions_5m, transactions_1h, transactions_6h, transactions_24h]):
                reasons.append("TXNS_NON_MONOTONIC")

        return GateVerdict(is_ok=(len(reasons) == 0), reasons=reasons)

from __future__ import annotations

from typing import Optional

from src.core.ai.chart_signal_provider import ChartAiSignalProvider
from src.core.ai.chart_structures import ChartAiSignal
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingChartAiSignalProvider:
    def __init__(self) -> None:
        self._delegate = ChartAiSignalProvider()

    def predict_market_signal(
            self,
            symbol: Optional[str],
            chain_name: Optional[str],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
            token_age_hours: Optional[float] = None,
    ) -> Optional[ChartAiSignal]:
        return self._delegate.predict_market_signal(
            symbol=symbol,
            chain_name=chain_name,
            pair_address=pair_address,
            timeframe_minutes=timeframe_minutes,
            lookback_minutes=lookback_minutes,
            token_age_hours=token_age_hours,
        )

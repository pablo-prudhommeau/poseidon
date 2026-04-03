from __future__ import annotations

from src.core.trading.trading_pipeline import TradingPipeline
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingJob:
    def __init__(self) -> None:
        self._pipeline = TradingPipeline()

    def run_once(self) -> None:
        self._pipeline.run_once()

    def run(self) -> None:
        self.run_once()

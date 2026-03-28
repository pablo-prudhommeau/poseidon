from __future__ import annotations

from src.core.jobs.trending.pipeline import TrendingPipeline
from src.logging.logger import get_logger

log = get_logger(__name__)


class TrendingJob:
    def __init__(self) -> None:
        self._pipeline = TrendingPipeline()

    def run_once(self) -> None:
        self._pipeline.run_once()

    def run(self) -> None:
        self.run_once()

from __future__ import annotations

from src.core.jobs.trending.pipeline import TrendingPipeline
from src.logging.logger import get_logger

log = get_logger(__name__)


class TrendingJob:
    """
    Backwards-compatible façade over the new trending pipeline.

    This class keeps the public API stable (run / run_once) while delegating the
    implementation to :class:`TrendingPipeline`.
    """

    def __init__(self) -> None:
        self._pipeline = TrendingPipeline()

    def run_once(self) -> None:
        """Execute one full trending evaluation cycle."""
        self._pipeline.run_once()

    def run(self) -> None:
        """Public entry-point to run one cycle. Kept for backwards compatibility."""
        self.run_once()

from __future__ import annotations

from threading import Lock
from typing import Optional

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelTransactionHeadFingerprint,
)
from src.core.aavesentinel.cache.aave_sentinel_cache_structures import AaveSentinelState
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_position_snapshot: Optional[AaveSentinelPositionSnapshot] = None
        self._cached_capital_flow_summary: Optional[AaveSentinelCapitalFlowSummary] = None
        self._last_seen_transaction_fingerprint: Optional[AaveSentinelTransactionHeadFingerprint] = None

    def update_position_snapshot(self, position_snapshot: Optional[AaveSentinelPositionSnapshot]) -> None:
        with self._lock:
            self._cached_position_snapshot = position_snapshot
            logger.debug(
                "[AAVESENTINEL][CACHE] Position snapshot updated (available=%s)",
                position_snapshot is not None,
            )

    def update_capital_flow_summary(self, capital_flow_summary: AaveSentinelCapitalFlowSummary) -> None:
        with self._lock:
            self._cached_capital_flow_summary = capital_flow_summary
            logger.debug(
                "[AAVESENTINEL][CACHE] Capital flow summary updated net_capital_usd=%0.2f",
                capital_flow_summary.net_capital_deployed_usd,
            )

    def update_last_seen_transaction_fingerprint(
            self,
            transaction_fingerprint: AaveSentinelTransactionHeadFingerprint,
    ) -> None:
        with self._lock:
            self._last_seen_transaction_fingerprint = transaction_fingerprint
            logger.debug("[AAVESENTINEL][CACHE] Transaction fingerprint updated")

    def get_aave_sentinel_state(self) -> AaveSentinelState:
        with self._lock:
            return AaveSentinelState(
                position_snapshot=self._cached_position_snapshot,
                capital_flow_summary=self._cached_capital_flow_summary,
                last_seen_transaction_fingerprint=self._last_seen_transaction_fingerprint,
            )

    def get_last_seen_transaction_fingerprint(self) -> Optional[AaveSentinelTransactionHeadFingerprint]:
        with self._lock:
            return self._last_seen_transaction_fingerprint


aave_sentinel_state_cache = AaveSentinelCache()

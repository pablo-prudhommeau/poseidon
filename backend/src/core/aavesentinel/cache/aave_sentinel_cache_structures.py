from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelTransactionHeadFingerprint,
)


class AaveSentinelState(BaseModel):
    position_snapshot: Optional[AaveSentinelPositionSnapshot] = None
    capital_flow_summary: Optional[AaveSentinelCapitalFlowSummary] = None
    last_seen_transaction_fingerprint: Optional[AaveSentinelTransactionHeadFingerprint] = None

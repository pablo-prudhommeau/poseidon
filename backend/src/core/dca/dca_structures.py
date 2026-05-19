from enum import Enum
from typing import List

from pydantic import BaseModel


class DcaStrategyStatus(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DcaOrderStatus(Enum):
    PENDING = "PENDING"
    WAITING_USER_APPROVAL = "WAITING_USER_APPROVAL"
    APPROVED = "APPROVED"
    WITHDRAWN_FROM_AAVE = "WITHDRAWN_FROM_AAVE"
    SWAPPED = "SWAPPED"
    EXECUTED = "EXECUTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class DcaBacktestSeriesPoint(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class DcaBacktestMetadata(BaseModel):
    source_asset_symbol: str
    total_allocated_budget: float
    total_planned_executions: int
    final_dumb_average_unit_price: float
    final_smart_average_unit_price: float
    total_overheat_retentions: int


class DcaBacktestPayload(BaseModel):
    metadata: DcaBacktestMetadata
    dumb_dca_series: List[DcaBacktestSeriesPoint]
    smart_dca_series: List[DcaBacktestSeriesPoint]


class AllocationResult(BaseModel):
    spend_amount: float
    dry_powder_delta: float
    action_description: str

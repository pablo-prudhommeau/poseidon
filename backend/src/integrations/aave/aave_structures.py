from enum import Enum
from typing import Optional

from pydantic import BaseModel


class AaveLiveMetrics(BaseModel):
    supply_apy: float
    asset_out_price_usd: float


class AaveEvmTransactionConfirmationFailureKind(Enum):
    REVERTED = "REVERTED"
    CONFIRMATION_TIMEOUT = "CONFIRMATION_TIMEOUT"


class AaveEvmTransactionConfirmationOutcome(BaseModel):
    transaction_hash: Optional[str] = None
    is_confirmed: bool
    confirmation_failure_kind: Optional[AaveEvmTransactionConfirmationFailureKind] = None
    onchain_revert_reason: Optional[str] = None
    block_number: Optional[int] = None

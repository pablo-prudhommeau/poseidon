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


class AaveReserveIndexSnapshot(BaseModel):
    underlying_address: str
    liquidity_index: float
    variable_borrow_index: float


class AaveScaledBalanceSnapshot(BaseModel):
    underlying_address: str
    scaled_supply_balance: float
    scaled_debt_balance: float


class AaveAssetPriceUsdSnapshot(BaseModel):
    contract_address: str
    asset_price_usd: float


class AaveScaledBalanceBatchRequest(BaseModel):
    underlying_address: str
    a_token_address: str
    variable_debt_token_address: str
    decimal_count: int

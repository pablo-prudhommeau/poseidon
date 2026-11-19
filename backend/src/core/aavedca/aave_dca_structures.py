from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class AaveDcaStrategyStatus(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AaveDcaConfigurationError(RuntimeError):
    pass


class AaveDcaStrategyNotFoundError(Exception):
    pass


class AaveDcaStrategyStatusTransitionError(Exception):
    pass


class AaveDcaActiveStrategyConflictError(Exception):
    pass


class AaveDcaOrderStatus(Enum):
    PENDING = "PENDING"
    WAITING_USER_APPROVAL = "WAITING_USER_APPROVAL"
    AWAITING_WITHDRAW = "AWAITING_WITHDRAW"
    AWAITING_SWAP = "AWAITING_SWAP"
    AWAITING_SUPPLY = "AWAITING_SUPPLY"
    EXECUTED = "EXECUTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class AaveDcaAllocationDecision(Enum):
    AVERAGE_PRICE_PROTECTION_HALT = "AVERAGE_PRICE_PROTECTION_HALT"
    CONSERVATIVE_RETENTION_SCALED = "CONSERVATIVE_RETENTION_SCALED"
    AGGRESSIVE_DIP_ACCUMULATION_SCALED = "AGGRESSIVE_DIP_ACCUMULATION_SCALED"
    FALLBACK_NOMINAL_STRATEGY = "FALLBACK_NOMINAL_STRATEGY"


class AaveDcaPipelineOperationStep(Enum):
    WITHDRAW = "WITHDRAW"
    SWAP = "SWAP"
    SUPPLY = "SUPPLY"


class AaveDcaPipelineOperationStatus(Enum):
    BROADCASTED = "BROADCASTED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AaveDcaPipelinePreflightFailureReason(Enum):
    INSUFFICIENT_NATIVE_GAS_BALANCE = "INSUFFICIENT_NATIVE_GAS_BALANCE"
    INSUFFICIENT_AAVE_SUPPLY_BALANCE = "INSUFFICIENT_AAVE_SUPPLY_BALANCE"
    INSUFFICIENT_WALLET_SOURCE_BALANCE = "INSUFFICIENT_WALLET_SOURCE_BALANCE"
    INVALID_EXECUTION_AMOUNT = "INVALID_EXECUTION_AMOUNT"
    EMPTY_TARGET_BALANCE_POST_SWAP = "EMPTY_TARGET_BALANCE_POST_SWAP"
    LIFI_QUOTE_INVALID = "LIFI_QUOTE_INVALID"
    LIFI_TRANSACTION_REJECTED = "LIFI_TRANSACTION_REJECTED"
    PRE_SWAP_BALANCE_MISSING = "PRE_SWAP_BALANCE_MISSING"
    EMPTY_DEPOSIT_AMOUNT = "EMPTY_DEPOSIT_AMOUNT"
    ONCHAIN_EXECUTION_FAILED = "ONCHAIN_EXECUTION_FAILED"
    SWAP_AMOUNT_BELOW_ROUTE_MINIMUM = "SWAP_AMOUNT_BELOW_ROUTE_MINIMUM"
    MAX_RETRIES_EXCEEDED = "MAX_RETRIES_EXCEEDED"


class AaveDcaPipelineOnchainFailureRetryPolicy(Enum):
    TRANSIENT = "TRANSIENT"
    BLOCKING = "BLOCKING"


class AaveDcaTransientPipelineError(RuntimeError):
    pass


class AaveDcaBlockingPipelineError(RuntimeError):
    def __init__(self, reason: str, message: str = "") -> None:
        self.reason = reason
        super().__init__(message or reason)


class AaveDcaPipelinePreflightResult(BaseModel):
    is_successful: bool
    failure_reason: Optional[AaveDcaPipelinePreflightFailureReason] = None
    native_gas_balance_avax: Optional[float] = None
    aave_supply_balance: Optional[float] = None
    wallet_source_balance: Optional[float] = None
    required_execution_amount_base_units: int


class AaveDcaStrategyStatusChange(BaseModel):
    strategy_id: int
    previous_status: AaveDcaStrategyStatus
    status: AaveDcaStrategyStatus
    suspended_in_flight_order_count: int


class AaveDcaNativeGasRequirement(BaseModel):
    order_count: int
    gas_units_per_order: int
    max_fee_per_gas_wei: int
    estimated_gas_cost_avax: float
    minimum_reserve_avax: float
    required_balance_avax: float
    wallet_balance_avax: float
    missing_balance_avax: float
    is_sufficient: bool


class AaveDcaInsufficientNativeGasError(Exception):
    def __init__(self, native_gas_requirement: AaveDcaNativeGasRequirement) -> None:
        super().__init__(
            f"Insufficient AVAX for gas: wallet_balance={native_gas_requirement.wallet_balance_avax:.4f} "
            f"required_balance={native_gas_requirement.required_balance_avax:.4f} "
            f"missing_balance={native_gas_requirement.missing_balance_avax:.4f}"
        )
        self.native_gas_requirement = native_gas_requirement


class AaveDcaSwapPriceValidationResult(BaseModel):
    is_acceptable: bool
    deviation_expected_percent: float
    deviation_minimum_percent: float
    binance_reference_price_usd: float
    implied_expected_price_usd: float
    implied_minimum_price_usd: float


class AaveDcaPipelineOnchainFailureClassification(BaseModel):
    onchain_revert_reason: Optional[str] = None
    retry_policy: AaveDcaPipelineOnchainFailureRetryPolicy
    suspension_reason: AaveDcaPipelinePreflightFailureReason


class AaveDcaPipelineOnchainRevertRule(BaseModel):
    onchain_revert_reason: str
    retry_policy: AaveDcaPipelineOnchainFailureRetryPolicy
    suspension_reason: AaveDcaPipelinePreflightFailureReason


class AaveDcaPipelineOperation(BaseModel):
    step: AaveDcaPipelineOperationStep
    status: AaveDcaPipelineOperationStatus
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    transaction_hash: Optional[str] = None
    route_tool: Optional[str] = None
    source_amount_base_units: Optional[int] = None
    expected_output_base_units: Optional[int] = None
    minimum_output_base_units: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    pipeline_attempt_number: Optional[int] = None
    nonce: Optional[int] = None
    pre_swap_target_balance_base_units: Optional[int] = None


class AaveDcaPipelineOperationDetails(BaseModel):
    route_tool: Optional[str] = None
    source_amount_base_units: Optional[int] = None
    expected_output_base_units: Optional[int] = None
    minimum_output_base_units: Optional[int] = None
    pre_swap_target_balance_base_units: Optional[int] = None


class AaveDcaOrderPipelineOperations(BaseModel):
    initialized_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    pipeline_operations: List[AaveDcaPipelineOperation]


class AaveDcaBacktestSeriesPoint(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class AaveDcaBacktestMetadata(BaseModel):
    source_asset_symbol: str
    total_allocated_budget: float
    total_planned_executions: int
    final_dumb_average_unit_price: float
    final_smart_average_unit_price: float
    total_overheat_retentions: int


class AaveDcaBacktestPayload(BaseModel):
    metadata: AaveDcaBacktestMetadata
    dumb_dca_series: List[AaveDcaBacktestSeriesPoint]
    smart_dca_series: List[AaveDcaBacktestSeriesPoint]


class AllocationResult(BaseModel):
    spend_amount: float
    dry_powder_delta: float
    allocation_decision: AaveDcaAllocationDecision
    allocation_multiplier: float

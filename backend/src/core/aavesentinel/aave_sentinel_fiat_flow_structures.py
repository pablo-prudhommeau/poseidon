from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.core.utils.date_utils import get_current_local_datetime


class AaveSentinelFiatFlowDirection(str, Enum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class AaveSentinelTrackedStablecoin(BaseModel):
    symbol: str
    contract_address: str
    decimal_count: int
    requires_euro_conversion: bool = False


class AaveSentinelErc20TransferFlow(BaseModel):
    incoming_amount: float = 0.0
    outgoing_amount: float = 0.0


class AaveSentinelUniversalLedgerEntry(BaseModel):
    transaction_hash: str
    block_number: int = 0
    timestamp_seconds: int = 0
    native_sent_amount: float = 0.0
    native_received_amount: float = 0.0
    erc20_transfer_flows_by_contract: dict[str, AaveSentinelErc20TransferFlow] = Field(default_factory=dict)


class AaveSentinelClassifiedFiatFlow(BaseModel):
    transaction_hash: str
    block_number: int
    timestamp_seconds: int
    stablecoin_symbol: str
    direction: AaveSentinelFiatFlowDirection
    token_amount: float
    amount_usd: float


class AaveSentinelRawFiatFlowEvent(BaseModel):
    transaction_hash: str
    block_number: int
    timestamp_seconds: int
    stablecoin_symbol: str
    direction: AaveSentinelFiatFlowDirection
    token_amount: float
    requires_euro_conversion: bool


class AaveSentinelStablecoinFlowTotals(BaseModel):
    stablecoin_symbol: str
    total_inflow_token_amount: float = 0.0
    total_outflow_token_amount: float = 0.0
    total_inflow_usd: float = 0.0
    total_outflow_usd: float = 0.0


class AaveSentinelFiatFlowSummary(BaseModel):
    total_inflow_usd: float = 0.0
    total_outflow_usd: float = 0.0
    net_capital_deployed_usd: float = 0.0
    stablecoin_totals: list[AaveSentinelStablecoinFlowTotals] = Field(default_factory=list)
    classified_flows: list[AaveSentinelClassifiedFiatFlow] = Field(default_factory=list)
    is_available: bool = False
    refreshed_at: Optional[datetime] = None


def build_default_tracked_stablecoins() -> list[AaveSentinelTrackedStablecoin]:
    return [
        AaveSentinelTrackedStablecoin(
            symbol="USDC",
            contract_address="0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
            decimal_count=6,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="USDC.e",
            contract_address="0xA7D7079b0FEaA08C6127c16eC3914020F9328ae1",
            decimal_count=6,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="USDT",
            contract_address="0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7",
            decimal_count=6,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="USDT.e",
            contract_address="0xc7198437980c041c805a1edcba50c1ce5db95118",
            decimal_count=6,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="EURC",
            contract_address="0xc891eb4cbdeff6e073e859e987815ed1505c2acd",
            decimal_count=6,
            requires_euro_conversion=True,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="DAI.e",
            contract_address="0xd586e7f844cea2f87f50152665bcbc2c279d8d70",
            decimal_count=18,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="FRAX",
            contract_address="0xD24C2Ad096400B6FBcd2ad8B24E7acBc21A1da64",
            decimal_count=18,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="MIM",
            contract_address="0x130966628846bfd36ff31a822705796e8cb8c18d",
            decimal_count=18,
        ),
        AaveSentinelTrackedStablecoin(
            symbol="BUSD.e",
            contract_address="0x19860ccb0a68fd4213ab9d8266f7bbf05a8dde98",
            decimal_count=18,
        ),
    ]


def create_empty_fiat_flow_summary() -> AaveSentinelFiatFlowSummary:
    return AaveSentinelFiatFlowSummary(
        is_available=False,
        refreshed_at=get_current_local_datetime(),
    )

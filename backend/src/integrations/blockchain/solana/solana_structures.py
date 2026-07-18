from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason


class SolanaRpcFailureReason(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    JSON_RPC_ERROR = "JSON_RPC_ERROR"
    ENDPOINTS_EXHAUSTED = "ENDPOINTS_EXHAUSTED"
    NETWORK_ERROR = "NETWORK_ERROR"
    MISSING_ACCOUNT = "MISSING_ACCOUNT"
    INVALID_ACCOUNT_DATA = "INVALID_ACCOUNT_DATA"


class SolanaPriceParseResources(BaseModel):
    vault_balances_by_address: dict[str, int]
    mint_decimals_by_address: dict[str, int]

    def resolve_vault_balance_raw(self, vault_address: str) -> int | None:
        return self.vault_balances_by_address.get(vault_address)

    def resolve_mint_decimals(self, mint_address: str) -> int | None:
        return self.mint_decimals_by_address.get(mint_address)


class SolanaTransactionConfirmationResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    is_confirmed: bool
    failure_reason: Optional[BlockchainTransactionFailureReason]
    raw_error_text: str


class SolanaRpcEndpointRateLimitState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rpc_url: str
    cooldown_until_monotonic: float = 0.0
    request_timestamps_monotonic: list[float] = Field(default_factory=list)


class SolanaTransactionFeeBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_fee_lamports: int
    account_rent_lamports: int
    total_lamports: int
    total_sol: float
    total_usd: float
    swap_fee_usd: float


class SolanaPoolPriceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    price_in_quote_token: float
    quote_token_mint: str
    dex_identifier: str


class SolanaMintFreezeAuthoritySnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    mint_address: str
    freeze_authority_address: Optional[str]


class SolanaParsedMintAccountInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    freeze_authority_address: Optional[str]


class SolanaWalletTokenAccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token_account_address: str
    token_mint_address: str
    balance_raw: int
    owner_program_id: str
    account_state: str


class SolanaWalletSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wallet_address: str
    rpc_url: str
    token_accounts: list[SolanaWalletTokenAccountSnapshot]
    native_lamports: int
    fetched_at_monotonic: float


class SolanaTokenAccountRentBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_usd: float
    closable_usd: float
    pending_reclaim_usd: float
    locked_sol: float
    active_account_count: int
    closable_account_count: int
    pending_reclaim_account_count: int


SOLANA_WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"

SOLANA_SOL_DECIMALS = 9
SOLANA_PUMPFUN_TOKEN_DECIMALS = 6
SOLANA_SPL_TOKEN_BALANCE_OFFSET = 64
SOLANA_SPL_TOKEN_MINT_OFFSET = 0
SOLANA_SPL_TOKEN_DECIMALS_OFFSET = 44
SOLANA_SPL_TOKEN_ACCOUNT_DATA_LENGTH = 165
SOLANA_SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SOLANA_TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SOLANA_SUPPORTED_TOKEN_ACCOUNT_OWNER_PROGRAM_IDS: frozenset[str] = frozenset(
    {
        SOLANA_SPL_TOKEN_PROGRAM_ID,
        SOLANA_TOKEN_2022_PROGRAM_ID,
    },
)


class SolanaOnchainWalletContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wallet_snapshot: SolanaWalletSnapshot
    rent_breakdown: SolanaTokenAccountRentBreakdown
    stablecoin_balance_raw: float
    native_token_balance_raw: float
    native_token_balance_usd: float


class SolanaExecutedTradeAmounts(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    stablecoin_balance_delta_usd: float
    token_balance_delta_raw: int
    executed_token_quantity: float
    executed_token_price_usd: float

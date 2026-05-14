from pydantic import BaseModel, ConfigDict


class SolanaTransactionFeeBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_fee_lamports: int
    account_rent_lamports: int
    total_lamports: int
    total_sol: float
    total_usd: float


class SolanaPoolPriceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    price_in_quote_token: float
    quote_token_mint: str
    dex_identifier: str


SOLANA_WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"

SOLANA_KNOWN_STABLECOIN_MINTS: set[str] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

SOLANA_DEX_PROGRAM_IDS: dict[str, str] = {
    "pumpfun": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "raydium_amm_v4": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "raydium_clmm": "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "meteora": "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
    "orca": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
}

SOLANA_SOL_DECIMALS = 9
SOLANA_PUMPFUN_TOKEN_DECIMALS = 6
SOLANA_SPL_TOKEN_BALANCE_OFFSET = 64
SOLANA_SPL_TOKEN_MINT_OFFSET = 0
SOLANA_SPL_TOKEN_DECIMALS_OFFSET = 44

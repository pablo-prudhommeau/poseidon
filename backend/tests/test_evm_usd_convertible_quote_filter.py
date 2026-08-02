from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.evaluators.trading_evm_usd_convertible_quote_filter import (
    apply_evm_usd_convertible_quote_filter,
)
from src.core.trading.screener.trading_screener_structures import (
    TRADING_SCREENER_PROVIDER_DEXSCREENER,
    TradingScreenerEnvelope,
)
from src.core.trading.trading_helpers import build_trading_candidate
from src.core.trading.trading_structures import TradingCandidate, TradingDexMarketSnapshot
from src.integrations.blockchain.evm.blockchain_evm_price_reader import is_evm_quote_token_usd_convertible

BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
BSC_WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
BSC_SPCXB = "0xbe9D1568aA120e3F1f4eB85d928a2BC9B3dD3c9c"
BSC_TARGET_TOKEN = "0x1111111111111111111111111111111111111111"
BSC_PAIR_ADDRESS = "0x60c04117753e634fe2d0587493613aaccdd0329c"


def test_is_evm_quote_token_usd_convertible_accepts_stablecoin_and_wrapped_native() -> None:
    assert is_evm_quote_token_usd_convertible(BlockchainNetwork.BSC, BSC_USDT) is True
    assert is_evm_quote_token_usd_convertible(BlockchainNetwork.BSC, BSC_WBNB) is True


def test_is_evm_quote_token_usd_convertible_rejects_spcxb() -> None:
    assert is_evm_quote_token_usd_convertible(BlockchainNetwork.BSC, BSC_SPCXB) is False


def test_is_evm_quote_token_usd_convertible_rejects_empty_quote() -> None:
    assert is_evm_quote_token_usd_convertible(BlockchainNetwork.BSC, "   ") is False


def _build_market_snapshot() -> TradingDexMarketSnapshot:
    return TradingDexMarketSnapshot(
        price_usd=0.01,
        price_native=0.00001,
        token_age_hours=12.0,
        volume_m5_usd=1000.0,
        volume_h1_usd=5000.0,
        volume_h6_usd=10000.0,
        volume_h24_usd=20000.0,
        liquidity_usd=50000.0,
        price_change_percentage_m5=1.0,
        price_change_percentage_h1=2.0,
        price_change_percentage_h6=3.0,
        price_change_percentage_h24=4.0,
        transaction_count_m5=10,
        transaction_count_h1=50,
        transaction_count_h6=100,
        transaction_count_h24=200,
        buy_to_sell_ratio=1.5,
        market_cap_usd=500000.0,
        fully_diluted_valuation_usd=600000.0,
    )


def _build_candidate(
        blockchain_network: BlockchainNetwork,
        quote_token_address: str,
        symbol: str = "ASTEROID",
) -> TradingCandidate:
    token = Token(
        symbol=symbol,
        chain=blockchain_network,
        token_address=BSC_TARGET_TOKEN,
        pair_address=BSC_PAIR_ADDRESS,
        dex_id="pancakeswap",
    )
    payload: dict[str, object] = {
        "base_token": {
            "address": BSC_TARGET_TOKEN,
            "name": symbol,
            "symbol": symbol,
        },
        "quote_token": {
            "address": quote_token_address,
            "name": "Quote",
            "symbol": "QUOTE",
        },
        "pair_address": BSC_PAIR_ADDRESS,
        "chain_id": blockchain_network.value,
        "dex_id": "pancakeswap",
        "price_usd": 0.01,
    }
    return build_trading_candidate(
        token=token,
        market_snapshot=_build_market_snapshot(),
        screener_envelope=TradingScreenerEnvelope(
            provider_id=TRADING_SCREENER_PROVIDER_DEXSCREENER,
            payload=payload,
        ),
    )


def test_apply_evm_usd_convertible_quote_filter_rejects_spcxb_and_keeps_wbnb() -> None:
    spcxb_candidate = _build_candidate(BlockchainNetwork.BSC, BSC_SPCXB, symbol="ASTEROID")
    wbnb_candidate = _build_candidate(BlockchainNetwork.BSC, BSC_WBNB, symbol="GOOD")
    solana_candidate = _build_candidate(BlockchainNetwork.SOLANA, "So11111111111111111111111111111111111111112", symbol="SOLTOKEN")

    retained = apply_evm_usd_convertible_quote_filter(
        [spcxb_candidate, wbnb_candidate, solana_candidate],
    )

    retained_symbols = {candidate.token.symbol for candidate in retained}
    assert retained_symbols == {"GOOD", "SOLTOKEN"}

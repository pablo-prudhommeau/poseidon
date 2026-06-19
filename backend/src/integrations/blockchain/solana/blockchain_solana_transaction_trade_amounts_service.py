from __future__ import annotations

from typing import Optional

from solders.signature import Signature
from solders.transaction_status import EncodedConfirmedTransactionWithStatusMeta

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.blockchain.solana.solana_structures import SolanaExecutedTradeAmounts
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_DEPLOYABLE_STABLECOIN_DECIMALS = 6


def resolve_solana_executed_trade_amounts_from_transaction(
        transaction_signature: str,
        target_token_mint_address: str,
        token_decimals: int,
) -> Optional[SolanaExecutedTradeAmounts]:
    if not transaction_signature.strip():
        return None
    if not target_token_mint_address.strip():
        return None
    if token_decimals < 0:
        return None

    deployable_stablecoin_mint_address = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA).strip()
    if not deployable_stablecoin_mint_address:
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Missing deployable stablecoin mint address",
        )
        return None

    try:
        solana_signer = build_default_solana_signer()
    except Exception:
        logger.exception(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Solana signer unavailable for transaction_signature=%s",
            transaction_signature,
        )
        return None

    wallet_address = solana_signer.address
    pre_token_balances, post_token_balances = _fetch_confirmed_transaction_token_balances(
        solana_signer=solana_signer,
        transaction_signature=transaction_signature,
    )
    if pre_token_balances is None or post_token_balances is None:
        return None

    pre_balance_raw_by_mint = _build_owner_token_balance_raw_by_mint(
        token_balances=pre_token_balances,
        wallet_address=wallet_address,
    )
    post_balance_raw_by_mint = _build_owner_token_balance_raw_by_mint(
        token_balances=post_token_balances,
        wallet_address=wallet_address,
    )

    stablecoin_pre_balance_raw = pre_balance_raw_by_mint.get(deployable_stablecoin_mint_address, 0)
    stablecoin_post_balance_raw = post_balance_raw_by_mint.get(deployable_stablecoin_mint_address, 0)
    stablecoin_balance_delta_raw = stablecoin_post_balance_raw - stablecoin_pre_balance_raw

    token_pre_balance_raw = pre_balance_raw_by_mint.get(target_token_mint_address, 0)
    token_post_balance_raw = post_balance_raw_by_mint.get(target_token_mint_address, 0)
    token_balance_delta_raw = token_post_balance_raw - token_pre_balance_raw

    stablecoin_balance_delta_usd = stablecoin_balance_delta_raw / float(10 ** SOLANA_DEPLOYABLE_STABLECOIN_DECIMALS)
    executed_token_quantity = abs(token_balance_delta_raw) / float(10 ** token_decimals)
    if executed_token_quantity <= 0.0:
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Zero executed token quantity — "
            "transaction_signature=%s target_token_mint_address=%s token_balance_delta_raw=%d",
            transaction_signature,
            target_token_mint_address,
            token_balance_delta_raw,
        )
        return None

    executed_token_price_usd = abs(stablecoin_balance_delta_usd) / executed_token_quantity
    executed_trade_amounts = SolanaExecutedTradeAmounts(
        stablecoin_balance_delta_usd=stablecoin_balance_delta_usd,
        token_balance_delta_raw=token_balance_delta_raw,
        executed_token_quantity=executed_token_quantity,
        executed_token_price_usd=executed_token_price_usd,
    )
    logger.info(
        "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Parsed executed trade amounts — "
        "transaction_signature=%s target_token_mint_address=%s deployable_stablecoin_mint_address=%s "
        "stablecoin_balance_delta_usd=%.6f executed_token_quantity=%.12f executed_token_price_usd=%.12f",
        transaction_signature,
        target_token_mint_address,
        deployable_stablecoin_mint_address,
        executed_trade_amounts.stablecoin_balance_delta_usd,
        executed_trade_amounts.executed_token_quantity,
        executed_trade_amounts.executed_token_price_usd,
    )
    logger.debug(
        "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS][VERBOSE] token_balance_delta_raw=%d wallet_address=%s",
        token_balance_delta_raw,
        wallet_address,
    )
    return executed_trade_amounts


def _fetch_confirmed_transaction_token_balances(
        solana_signer,
        transaction_signature: str,
) -> tuple[Optional[list], Optional[list]]:
    from solana.rpc.commitment import Confirmed

    try:
        signature_object = Signature.from_string(transaction_signature)
    except Exception as exception:
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Invalid transaction signature — "
            "transaction_signature=%s error=%s",
            transaction_signature,
            exception,
        )
        return None, None

    try:
        response = solana_signer.client.get_transaction(
            signature_object,
            encoding="json",
            commitment=Confirmed,
            max_supported_transaction_version=0,
        )
    except Exception as exception:
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] get_transaction failed — "
            "transaction_signature=%s error=%s",
            transaction_signature,
            exception,
        )
        return None, None

    confirmed = response.value
    if confirmed is None:
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] No transaction value — transaction_signature=%s",
            transaction_signature,
        )
        return None, None

    if not isinstance(confirmed, EncodedConfirmedTransactionWithStatusMeta):
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Unexpected confirmed transaction type — "
            "transaction_signature=%s type=%s",
            transaction_signature,
            type(confirmed),
        )
        return None, None

    encoded_with_meta = confirmed.transaction
    meta = encoded_with_meta.meta
    if meta is None:
        logger.warning(
            "[BLOCKCHAIN][SOLANA][TRANSACTION][TRADE_AMOUNTS] Missing transaction meta — transaction_signature=%s",
            transaction_signature,
        )
        return None, None

    pre_token_balances = list(meta.pre_token_balances) if meta.pre_token_balances is not None else []
    post_token_balances = list(meta.post_token_balances) if meta.post_token_balances is not None else []
    return pre_token_balances, post_token_balances


def _build_owner_token_balance_raw_by_mint(
        token_balances: list,
        wallet_address: str,
) -> dict[str, int]:
    balance_raw_by_mint: dict[str, int] = {}
    for token_balance_entry in token_balances:
        owner_text = str(token_balance_entry.owner) if token_balance_entry.owner is not None else ""
        if owner_text != wallet_address:
            continue
        mint_text = str(token_balance_entry.mint)
        amount_raw_text = str(token_balance_entry.ui_token_amount.amount)
        amount_raw = int(amount_raw_text)
        existing_balance_raw = balance_raw_by_mint.get(mint_text, 0)
        balance_raw_by_mint[mint_text] = existing_balance_raw + amount_raw
    return balance_raw_by_mint

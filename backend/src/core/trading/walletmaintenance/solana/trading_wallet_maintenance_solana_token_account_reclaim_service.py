from __future__ import annotations

from datetime import timedelta

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_execution_swap_service import SWAP_EXECUTION_LOCK
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_structures import (
    TradingWalletMaintenanceSolanaReclaimableTokenAccount,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceChainReclaimResult,
    TradingWalletMaintenanceOperationStatus,
)
from src.core.utils.date_utils import format_datetime_to_local_iso, get_current_local_datetime
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.blockchain_solana_signer import SolanaSigner, build_default_solana_signer
from src.integrations.blockchain.solana.solana_onchain_wallet_context_service import (
    invalidate_solana_onchain_wallet_context_cache,
)
from src.integrations.blockchain.solana.solana_rpc_client import fetch_solana_native_balance_lamports
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_SUPPORTED_TOKEN_ACCOUNT_OWNER_PROGRAM_IDS,
    SolanaWalletTokenAccountSnapshot,
)
from src.integrations.blockchain.solana.solana_wallet_snapshot_service import (
    invalidate_solana_wallet_snapshot_cache,
    resolve_cached_token_account_last_activity_datetime,
    resolve_solana_wallet_snapshot,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_CLOSE_ACCOUNT_INSTRUCTION_INDEX = 9


def run_solana_dormant_token_account_reclaim() -> TradingWalletMaintenanceChainReclaimResult:
    blockchain_network = BlockchainNetwork.SOLANA
    try:
        signer = build_default_solana_signer()
        wallet_address = signer.address
    except Exception:
        logger.exception(
            "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Signer unavailable — "
            "blockchain_network=%s reason=signer_unavailable",
            blockchain_network.value,
        )
        return TradingWalletMaintenanceChainReclaimResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="signer_unavailable",
        )

    rpc_url = resolve_rpc_url_for_chain(blockchain_network)
    try:
        wallet_snapshot = resolve_solana_wallet_snapshot(force_refresh=True)
        rpc_url = wallet_snapshot.rpc_url
        token_accounts = wallet_snapshot.token_accounts
    except BlockchainRpcUnavailableError:
        logger.warning(
            "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Wallet snapshot unavailable — "
            "blockchain_network=%s wallet_address=%s reason=rpc_unavailable",
            blockchain_network.value,
            wallet_address,
        )
        return TradingWalletMaintenanceChainReclaimResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="rpc_unavailable",
        )

    reclaimable_accounts = _resolve_reclaimable_token_accounts(
        rpc_url=rpc_url,
        token_accounts=token_accounts,
    )

    if not reclaimable_accounts:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Scan completed — "
            "blockchain_network=%s wallet_address=%s reclaimable_account_count=0 reason=no_reclaimable_accounts",
            blockchain_network.value,
            wallet_address,
        )
        return TradingWalletMaintenanceChainReclaimResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.NOT_REQUIRED,
            reason="no_reclaimable_accounts",
        )

    batch_size = settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_BATCH_SIZE
    transaction_signatures: list[str] = []
    reclaimed_account_count = 0
    reclaimed_lamports = 0

    for batch_start_index in range(0, len(reclaimable_accounts), batch_size):
        batch_accounts = reclaimable_accounts[batch_start_index:batch_start_index + batch_size]
        native_balance_before_lamports = fetch_solana_native_balance_lamports(rpc_url, wallet_address)
        if native_balance_before_lamports is None:
            native_balance_before_lamports = 0
        try:
            with SWAP_EXECUTION_LOCK:
                transaction_signature = _broadcast_close_token_accounts_transaction(
                    signer=signer,
                    reclaimable_accounts=batch_accounts,
                )
                confirmation_result = signer.confirm_transaction(transaction_signature)
                is_confirmed = confirmation_result.is_confirmed
                if not is_confirmed:
                    raise RuntimeError(f"Reclaim transaction {transaction_signature} failed confirmation")
        except Exception:
            logger.exception(
                "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Batch reclaim failed — "
                "blockchain_network=%s wallet_address=%s reclaimable_account_count=%d reason=reclaim_execution_failed",
                blockchain_network.value,
                wallet_address,
                len(batch_accounts),
            )
            if reclaimed_account_count == 0:
                return TradingWalletMaintenanceChainReclaimResult(
                    blockchain_network=blockchain_network,
                    status=TradingWalletMaintenanceOperationStatus.FAILED,
                    reason="reclaim_execution_failed",
                )
            break

        native_balance_after_lamports = fetch_solana_native_balance_lamports(rpc_url, wallet_address)
        if native_balance_after_lamports is None:
            native_balance_after_lamports = native_balance_before_lamports
        reclaimed_lamports += max(0, native_balance_after_lamports - native_balance_before_lamports)
        reclaimed_account_count += len(batch_accounts)
        transaction_signatures.append(transaction_signature)
        logger.info(
            "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Closed empty token accounts — "
            "blockchain_network=%s wallet_address=%s reclaimable_account_count=%d transaction_signature=%s "
            "native_balance_delta_lamports=%d",
            blockchain_network.value,
            wallet_address,
            len(batch_accounts),
            transaction_signature,
            max(0, native_balance_after_lamports - native_balance_before_lamports),
        )

    if reclaimed_account_count > 0:
        invalidate_solana_wallet_snapshot_cache()
        invalidate_solana_onchain_wallet_context_cache()

    return TradingWalletMaintenanceChainReclaimResult(
        blockchain_network=blockchain_network,
        status=TradingWalletMaintenanceOperationStatus.SUCCESS,
        reason="reclaim_executed",
        reclaimed_account_count=reclaimed_account_count,
        reclaimed_lamports=reclaimed_lamports,
        transaction_signatures=transaction_signatures,
    )


def _resolve_reclaimable_token_accounts(
        rpc_url: str,
        token_accounts: list[SolanaWalletTokenAccountSnapshot],
) -> list[TradingWalletMaintenanceSolanaReclaimableTokenAccount]:
    stablecoin_address = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    inactive_cutoff = get_current_local_datetime() - timedelta(hours=settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_INACTIVE_HOURS)
    mint_addresses_with_non_zero_balance = _resolve_mint_addresses_with_non_zero_balance(token_accounts)

    reclaimable_accounts: list[TradingWalletMaintenanceSolanaReclaimableTokenAccount] = []
    for token_account in token_accounts:
        if token_account.balance_raw != 0:
            continue
        if token_account.token_mint_address == stablecoin_address:
            continue
        if token_account.owner_program_id not in SOLANA_SUPPORTED_TOKEN_ACCOUNT_OWNER_PROGRAM_IDS:
            continue
        if token_account.token_mint_address in mint_addresses_with_non_zero_balance:
            logger.debug(
                "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Skipping empty token account — "
                "token_account_address=%s token_mint_address=%s reason=mint_has_non_zero_balance",
                token_account.token_account_address,
                token_account.token_mint_address,
            )
            continue

        last_activity_timestamp = resolve_cached_token_account_last_activity_datetime(
            rpc_url=rpc_url,
            token_account_address=token_account.token_account_address,
        )
        if last_activity_timestamp is None:
            logger.debug(
                "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Skipping empty token account — "
                "token_account_address=%s token_mint_address=%s reason=no_on_chain_transaction_history",
                token_account.token_account_address,
                token_account.token_mint_address,
            )
            continue
        if last_activity_timestamp >= inactive_cutoff:
            logger.debug(
                "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Skipping empty token account — "
                "token_account_address=%s token_mint_address=%s last_activity_timestamp=%s reason=recent_on_chain_activity",
                token_account.token_account_address,
                token_account.token_mint_address,
                format_datetime_to_local_iso(last_activity_timestamp),
            )
            continue

        last_activity_timestamp_iso = format_datetime_to_local_iso(last_activity_timestamp)
        if last_activity_timestamp_iso is None:
            continue

        reclaimable_accounts.append(
            TradingWalletMaintenanceSolanaReclaimableTokenAccount(
                token_account_address=token_account.token_account_address,
                token_mint_address=token_account.token_mint_address,
                owner_program_id=token_account.owner_program_id,
                last_activity_timestamp_iso=last_activity_timestamp_iso,
            )
        )

    logger.debug(
        "[TRADING][WALLETMAINTENANCE][SOLANA][TOKEN_ACCOUNT][RECLAIM] Reclaimable token account scan completed — "
        "wallet_token_account_count=%d reclaimable_account_count=%d inactive_cutoff_timestamp=%s",
        len(token_accounts),
        len(reclaimable_accounts),
        format_datetime_to_local_iso(inactive_cutoff),
    )
    return reclaimable_accounts


def _resolve_mint_addresses_with_non_zero_balance(
        token_accounts: list[SolanaWalletTokenAccountSnapshot],
) -> set[str]:
    mint_addresses_with_non_zero_balance: set[str] = set()
    for token_account in token_accounts:
        if token_account.balance_raw != 0:
            mint_addresses_with_non_zero_balance.add(token_account.token_mint_address)
    return mint_addresses_with_non_zero_balance


def _broadcast_close_token_accounts_transaction(
        signer: SolanaSigner,
        reclaimable_accounts: list[TradingWalletMaintenanceSolanaReclaimableTokenAccount],
) -> str:
    owner_pubkey = signer.keypair.pubkey()
    close_instructions: list[Instruction] = []

    for reclaimable_account in reclaimable_accounts:
        token_program_pubkey = Pubkey.from_string(reclaimable_account.owner_program_id)
        token_account_pubkey = Pubkey.from_string(reclaimable_account.token_account_address)
        instruction_data = bytes([SOLANA_CLOSE_ACCOUNT_INSTRUCTION_INDEX])
        account_metas = [
            AccountMeta(pubkey=token_account_pubkey, is_signer=False, is_writable=True),
            AccountMeta(pubkey=owner_pubkey, is_signer=False, is_writable=True),
            AccountMeta(pubkey=owner_pubkey, is_signer=True, is_writable=False),
        ]
        close_instructions.append(
            Instruction(
                program_id=token_program_pubkey,
                data=instruction_data,
                accounts=account_metas,
            )
        )

    latest_blockhash_response = signer.client.get_latest_blockhash()
    recent_blockhash_value = latest_blockhash_response.value.blockhash
    recent_blockhash = Hash.from_string(str(recent_blockhash_value))
    message = MessageV0.try_compile(
        payer=owner_pubkey,
        instructions=close_instructions,
        address_lookup_table_accounts=[],
        recent_blockhash=recent_blockhash,
    )
    signed_transaction = VersionedTransaction(message, [signer.keypair])
    signed_transaction_bytes = bytes(signed_transaction)
    return signer.broadcast_presigned_transaction(signed_transaction_bytes)

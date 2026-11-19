from __future__ import annotations

import asyncio
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract
from web3.exceptions import ContractLogicError, TimeExhausted, TransactionNotFound
from web3.types import TxParams, TxReceipt

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_abis import (
    AAVE_POOL_ABI,
    ERC20_ABI,
    ADDRESS_PROVIDER_ABI,
    AAVE_ORACLE_ABI
)
from src.integrations.aave.aave_structures import (
    AaveEvmFeeParameters,
    AaveEvmTransactionBroadcast,
    AaveEvmTransactionConfirmationFailureKind,
    AaveEvmTransactionConfirmationOutcome,
)
from src.integrations.aave.aave_structures import AaveLiveMetrics
from src.integrations.blockchain.blockchain_execution_constants import (
    AAVE_EVM_APPROVE_GAS_LIMIT,
    AAVE_EVM_POOL_OPERATION_GAS_LIMIT,
    AAVE_EVM_TRANSACTION_RECEIPT_RECHECK_DELAY_SECONDS,
    BLOCKCHAIN_TRANSACTION_CONFIRMATION_TIMEOUT_SECONDS,
    EVM_SWAP_GAS_BUFFER_MULTIPLIER,
)
from src.integrations.blockchain.blockchain_utils import normalize_evm_transaction_hash
from src.integrations.blockchain.evm.blockchain_evm_revert_utils import (
    decode_evm_revert_reason_from_contract_logic_error,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)
Account.enable_unaudited_hdwallet_features()


class AaveExecutor:
    _instance = None

    def __new__(cls) -> AaveExecutor:
        if not cls._instance:
            cls._instance = super(AaveExecutor, cls).__new__(cls)
            cls._instance.is_initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self.is_initialized:
            return

        self.web3_clients: dict[BlockchainNetwork, AsyncWeb3] = {}
        self.pool_contracts: dict[BlockchainNetwork, AsyncContract] = {}
        self.wallet_address: str = ""
        self.private_key: str = ""

        self.is_initialized = True

    def get_wallet_address(self) -> str:
        return self.wallet_address

    async def resolve_transaction_confirmation_outcome(
            self,
            chain: BlockchainNetwork,
            transaction_hash_hex: str,
            submitted_gas_limit: Optional[int] = None,
    ) -> AaveEvmTransactionConfirmationOutcome:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        timeout_seconds = BLOCKCHAIN_TRANSACTION_CONFIRMATION_TIMEOUT_SECONDS
        try:
            receipt = await client.eth.wait_for_transaction_receipt(transaction_hash_hex, timeout=timeout_seconds)
        except TimeExhausted:
            logger.warning(
                "[AAVE][EXECUTOR][CONFIRM] Transaction %s confirmation timed out after %ss",
                transaction_hash_hex,
                timeout_seconds,
            )
            return AaveEvmTransactionConfirmationOutcome(
                transaction_hash=transaction_hash_hex,
                is_confirmed=False,
                confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.CONFIRMATION_TIMEOUT,
            )
        except Exception as exception:
            logger.exception(
                "[AAVE][EXECUTOR][CONFIRM] Error waiting for transaction receipt %s: %s",
                transaction_hash_hex,
                exception,
            )
            raise RuntimeError(
                f"Transaction receipt wait failed for {transaction_hash_hex}"
            ) from exception

        return await self._build_confirmation_outcome_from_receipt(
            chain=chain,
            transaction_hash_hex=transaction_hash_hex,
            receipt=receipt,
            submitted_gas_limit=submitted_gas_limit,
        )

    async def _build_confirmation_outcome_from_receipt(
            self,
            chain: BlockchainNetwork,
            transaction_hash_hex: str,
            receipt: TxReceipt,
            submitted_gas_limit: Optional[int],
    ) -> AaveEvmTransactionConfirmationOutcome:
        receipt_status: Optional[int] = None
        receipt_block_number: Optional[int] = None
        if receipt is not None and receipt.get("status") is not None:
            receipt_status = int(receipt["status"])
        if receipt is not None and receipt.get("blockNumber") is not None:
            receipt_block_number = int(receipt["blockNumber"])

        if receipt_status == 1:
            logger.debug("[AAVE][EXECUTOR][CONFIRM] Transaction confirmed: %s", transaction_hash_hex)
            return AaveEvmTransactionConfirmationOutcome(
                transaction_hash=transaction_hash_hex,
                is_confirmed=True,
                block_number=receipt_block_number,
            )

        gas_used: Optional[int] = None
        if receipt is not None and receipt.get("gasUsed") is not None:
            gas_used = int(receipt["gasUsed"])

        onchain_revert_reason: Optional[str] = None
        if receipt_block_number is not None:
            onchain_revert_reason = await self._decode_reverted_transaction_reason(
                chain=chain,
                transaction_hash_hex=transaction_hash_hex,
                receipt_block_number=receipt_block_number,
            )

        logger.warning(
            "[AAVE][EXECUTOR][CONFIRM] Transaction %s failed on-chain status=%s gas_used=%s submitted_gas_limit=%s revert_reason=%s",
            transaction_hash_hex,
            receipt_status,
            gas_used,
            submitted_gas_limit,
            onchain_revert_reason,
        )
        return AaveEvmTransactionConfirmationOutcome(
            transaction_hash=transaction_hash_hex,
            is_confirmed=False,
            confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REVERTED,
            onchain_revert_reason=onchain_revert_reason,
            block_number=receipt_block_number,
        )

    async def _decode_reverted_transaction_reason(
            self,
            chain: BlockchainNetwork,
            transaction_hash_hex: str,
            receipt_block_number: int,
    ) -> Optional[str]:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        original_transaction = await client.eth.get_transaction(transaction_hash_hex)
        simulation_block_number: int = max(receipt_block_number - 1, 0)
        call_transaction: TxParams = {
            "from": original_transaction["from"],
            "to": original_transaction["to"],
            "data": original_transaction["input"],
            "value": original_transaction.get("value", 0),
            "gas": original_transaction.get("gas", 0),
        }
        try:
            await client.eth.call(call_transaction, simulation_block_number)
            return None
        except ContractLogicError as contract_logic_error:
            revert_data_hex: Optional[str] = None
            if contract_logic_error.data is not None:
                revert_data_hex = str(contract_logic_error.data)
            return decode_evm_revert_reason_from_contract_logic_error(
                error_message=str(contract_logic_error),
                revert_data_hex=revert_data_hex,
            )
        except Exception as exception:
            logger.warning(
                "[AAVE][EXECUTOR][CONFIRM] Failed to replay reverted transaction %s at block %s: %s",
                transaction_hash_hex,
                simulation_block_number,
                exception,
            )
            return None

    async def simulate_evm_transaction_before_broadcast(
            self,
            chain: BlockchainNetwork,
            to_address: str,
            transaction_calldata: str,
            transaction_value_wei: int,
            gas_limit: int,
    ) -> Optional[str]:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        checksum_to = AsyncWeb3.to_checksum_address(to_address)
        call_transaction: TxParams = {
            "from": self.wallet_address,
            "to": checksum_to,
            "data": transaction_calldata,
            "value": transaction_value_wei,
            "gas": gas_limit,
        }
        try:
            await client.eth.call(call_transaction, "latest")
            return None
        except ContractLogicError as contract_logic_error:
            revert_data_hex: Optional[str] = None
            if contract_logic_error.data is not None:
                revert_data_hex = str(contract_logic_error.data)
            return decode_evm_revert_reason_from_contract_logic_error(
                error_message=str(contract_logic_error),
                revert_data_hex=revert_data_hex,
            )
        except Exception as exception:
            logger.warning(
                "[AAVE][EXECUTOR][SIMULATE] Pre-broadcast simulation failed for target=%s: %s",
                checksum_to,
                exception,
            )
            return str(exception)

    async def _initialize_provider(self, chain: BlockchainNetwork) -> None:
        if chain in self.web3_clients:
            return

        if not settings.AAVE_DCA_WALLET_MNEMONIC:
            logger.error("[AAVE][EXECUTOR][INIT] Mnemonic configuration is missing")
            raise ValueError("Mnemonic configuration is missing.")

        account: LocalAccount = Account.from_mnemonic(
            settings.AAVE_DCA_WALLET_MNEMONIC,
            account_path=f"m/44'/60'/0'/0/{settings.AAVE_DCA_WALLET_DERIVATION_INDEX}"
        )
        self.private_key = account.key.hex()
        self.wallet_address = account.address

        if chain == BlockchainNetwork.AVALANCHE:
            from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain

            pool_address = settings.AAVE_POOL_V3_ADDRESS
        else:
            logger.error("[AAVE][EXECUTOR][INIT] Chain '%s' is not supported", chain.value)
            raise ValueError(f"Chain '{chain.value}' is not supported for Aave.")

        client = resolve_async_web3_provider_for_chain(chain)
        self.web3_clients[chain] = client

        pool_address_checksum = AsyncWeb3.to_checksum_address(pool_address)
        self.pool_contracts[chain] = client.eth.contract(address=pool_address_checksum, abi=AAVE_POOL_ABI)

        logger.info("[AAVE][EXECUTOR][INIT] Provider initialized for chain: %s", chain)

    async def _resolve_eip1559_fee_parameters(self, chain: BlockchainNetwork) -> AaveEvmFeeParameters:
        client = self.web3_clients[chain]
        latest_block = await client.eth.get_block("latest")
        network_base_fee: int = int(latest_block.get("baseFeePerGas") or 0)

        try:
            max_priority_fee: int = int(await client.eth.max_priority_fee)
        except Exception as exception:
            logger.exception("[AAVE][EXECUTOR][FEE] Max priority fee unavailable, falling back to 1 gwei: %s", exception)
            max_priority_fee = int(AsyncWeb3.to_wei(1, "gwei"))

        return AaveEvmFeeParameters(
            max_priority_fee_per_gas_wei=max_priority_fee,
            max_fee_per_gas_wei=(network_base_fee * 2) + max_priority_fee,
        )

    async def fetch_max_fee_per_gas_wei(self, chain: BlockchainNetwork) -> int:
        await self._initialize_provider(chain)
        fee_parameters: AaveEvmFeeParameters = await self._resolve_eip1559_fee_parameters(chain)
        logger.debug("[AAVE][EXECUTOR][FEE] Max fee per gas resolved: %s wei", fee_parameters.max_fee_per_gas_wei)
        return fee_parameters.max_fee_per_gas_wei

    async def _build_eip1559_transaction_parameters(
            self,
            chain: BlockchainNetwork,
            transaction_parameters: TxParams,
            gas_limit: int,
    ) -> TxParams:
        client = self.web3_clients[chain]
        fee_parameters: AaveEvmFeeParameters = await self._resolve_eip1559_fee_parameters(chain)
        chain_identifier: int = await client.eth.chain_id

        merged_transaction_parameters: TxParams = {
            **transaction_parameters,
            "type": 2,
            "chainId": chain_identifier,
            "gas": gas_limit,
            "maxPriorityFeePerGas": fee_parameters.max_priority_fee_per_gas_wei,
            "maxFeePerGas": fee_parameters.max_fee_per_gas_wei,
        }
        if "gasPrice" in merged_transaction_parameters:
            del merged_transaction_parameters["gasPrice"]

        logger.debug(
            "[AAVE][EXECUTOR][BUILD] EIP-1559 transaction prepared: nonce=%s gas_limit=%s max_fee_per_gas=%s",
            merged_transaction_parameters.get("nonce"),
            gas_limit,
            fee_parameters.max_fee_per_gas_wei,
        )
        return merged_transaction_parameters

    async def _resolve_pending_transaction_nonce(self, chain: BlockchainNetwork) -> int:
        client = self.web3_clients[chain]
        return int(await client.eth.get_transaction_count(self.wallet_address, "pending"))

    async def ensure_erc20_allowance(
            self,
            chain: BlockchainNetwork,
            token_address: str,
            spender_address: str,
            required_amount_wei: int,
    ) -> None:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]

        checksum_token = AsyncWeb3.to_checksum_address(token_address)
        checksum_spender = AsyncWeb3.to_checksum_address(spender_address)
        token_contract = client.eth.contract(address=checksum_token, abi=ERC20_ABI)

        current_allowance: int = int(
            await token_contract.functions.allowance(self.wallet_address, checksum_spender).call()
        )
        if current_allowance == required_amount_wei:
            logger.debug(
                "[AAVE][EXECUTOR][ALLOWANCE] Existing allowance already equals the required amount for spender=%s allowance_wei=%s",
                checksum_spender,
                current_allowance,
            )
            return

        logger.info(
            "[AAVE][EXECUTOR][ALLOWANCE] Setting allowance to the exact required amount for spender=%s allowance_wei=%s required_wei=%s",
            checksum_spender,
            current_allowance,
            required_amount_wei,
        )
        await self._approve_erc20_spending(
            chain=chain,
            token_contract=token_contract,
            checksum_spender=checksum_spender,
            approved_amount_wei=required_amount_wei,
        )

    async def reset_erc20_allowance(
            self,
            chain: BlockchainNetwork,
            token_address: str,
            spender_address: str,
    ) -> None:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]

        checksum_token = AsyncWeb3.to_checksum_address(token_address)
        checksum_spender = AsyncWeb3.to_checksum_address(spender_address)
        token_contract = client.eth.contract(address=checksum_token, abi=ERC20_ABI)

        current_allowance: int = int(
            await token_contract.functions.allowance(self.wallet_address, checksum_spender).call()
        )
        if current_allowance == 0:
            logger.debug("[AAVE][EXECUTOR][ALLOWANCE] Allowance already reset for spender=%s", checksum_spender)
            return

        logger.info(
            "[AAVE][EXECUTOR][ALLOWANCE] Resetting allowance to zero for spender=%s allowance_wei=%s",
            checksum_spender,
            current_allowance,
        )
        await self._approve_erc20_spending(
            chain=chain,
            token_contract=token_contract,
            checksum_spender=checksum_spender,
            approved_amount_wei=0,
        )

    async def _approve_erc20_spending(
            self,
            chain: BlockchainNetwork,
            token_contract: AsyncContract,
            checksum_spender: str,
            approved_amount_wei: int,
    ) -> None:
        client = self.web3_clients[chain]
        nonce: int = await self._resolve_pending_transaction_nonce(chain)
        approve_transaction: TxParams = await token_contract.functions.approve(
            checksum_spender,
            approved_amount_wei,
        ).build_transaction({
            "from": self.wallet_address,
            "nonce": nonce,
        })
        approve_transaction = await self._build_eip1559_transaction_parameters(
            chain=chain,
            transaction_parameters=approve_transaction,
            gas_limit=AAVE_EVM_APPROVE_GAS_LIMIT,
        )
        signed_approval = client.eth.account.sign_transaction(approve_transaction, self.private_key)
        approval_transaction_hash = await client.eth.send_raw_transaction(signed_approval.raw_transaction)
        approval_confirmation_outcome = await self.resolve_transaction_confirmation_outcome(
            chain,
            normalize_evm_transaction_hash(approval_transaction_hash),
        )
        if not approval_confirmation_outcome.is_confirmed:
            raise RuntimeError(f"ERC20 allowance approval not confirmed for spender {checksum_spender}")

    async def broadcast_raw_evm_transaction(
            self,
            chain: BlockchainNetwork,
            to_address: str,
            transaction_calldata: str,
            transaction_value_wei: int,
            gas_limit: int,
    ) -> AaveEvmTransactionBroadcast:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        checksum_to = AsyncWeb3.to_checksum_address(to_address)

        if gas_limit <= 0:
            raise ValueError("Swap gas limit must be a strictly positive integer provided by LI.FI routing quote")

        nonce: int = await self._resolve_pending_transaction_nonce(chain)
        buffered_swap_gas_limit: int = int(gas_limit * EVM_SWAP_GAS_BUFFER_MULTIPLIER)
        raw_transaction: TxParams = {
            "from": self.wallet_address,
            "to": checksum_to,
            "data": transaction_calldata,
            "value": transaction_value_wei,
            "nonce": nonce,
        }
        raw_transaction = await self._build_eip1559_transaction_parameters(
            chain=chain,
            transaction_parameters=raw_transaction,
            gas_limit=buffered_swap_gas_limit,
        )
        signed_transaction = client.eth.account.sign_transaction(raw_transaction, self.private_key)
        transaction_hash = await client.eth.send_raw_transaction(signed_transaction.raw_transaction)
        transaction_hash_hex = normalize_evm_transaction_hash(transaction_hash)

        logger.info("[AAVE][EXECUTOR][SWAP] Transaction sent: %s nonce=%s", transaction_hash_hex, nonce)
        return AaveEvmTransactionBroadcast(
            transaction_hash=transaction_hash_hex,
            nonce=nonce,
            submitted_gas_limit=buffered_swap_gas_limit,
        )

    async def inspect_broadcast_transaction(
            self,
            chain: BlockchainNetwork,
            transaction_hash_hex: str,
            nonce: int,
    ) -> Optional[AaveEvmTransactionConfirmationOutcome]:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]

        confirmed_transaction_count: int = int(await client.eth.get_transaction_count(self.wallet_address, "latest"))
        if confirmed_transaction_count <= nonce:
            logger.info(
                "[AAVE][EXECUTOR][INSPECT] Transaction %s is still pending: nonce=%s confirmed_transaction_count=%s",
                transaction_hash_hex,
                nonce,
                confirmed_transaction_count,
            )
            return None

        receipt: Optional[TxReceipt] = await self._fetch_mined_transaction_receipt(chain, transaction_hash_hex)
        if receipt is None:
            await asyncio.sleep(AAVE_EVM_TRANSACTION_RECEIPT_RECHECK_DELAY_SECONDS)
            receipt = await self._fetch_mined_transaction_receipt(chain, transaction_hash_hex)

        if receipt is not None:
            logger.debug("[AAVE][EXECUTOR][INSPECT] Receipt found for transaction %s", transaction_hash_hex)
            return await self._build_confirmation_outcome_from_receipt(
                chain=chain,
                transaction_hash_hex=transaction_hash_hex,
                receipt=receipt,
                submitted_gas_limit=None,
            )

        logger.warning(
            "[AAVE][EXECUTOR][INSPECT] Transaction %s has no receipt while nonce=%s is consumed: replaced or dropped",
            transaction_hash_hex,
            nonce,
        )
        return AaveEvmTransactionConfirmationOutcome(
            transaction_hash=transaction_hash_hex,
            is_confirmed=False,
            confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REPLACED_OR_DROPPED,
        )

    async def _fetch_mined_transaction_receipt(
            self,
            chain: BlockchainNetwork,
            transaction_hash_hex: str,
    ) -> Optional[TxReceipt]:
        client = self.web3_clients[chain]
        try:
            return await client.eth.get_transaction_receipt(transaction_hash_hex)
        except TransactionNotFound as exception:
            logger.exception(
                "[AAVE][EXECUTOR][INSPECT] No receipt for transaction %s although its nonce is consumed: %s",
                transaction_hash_hex,
                exception,
            )
            return None

    async def fetch_native_gas_balance_avax(self, chain: BlockchainNetwork) -> float:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        balance_wei: int = await client.eth.get_balance(self.wallet_address)
        return float(balance_wei) / 1e18

    async def fetch_supply_apy(self, chain: BlockchainNetwork, asset_address: str) -> float:
        await self._initialize_provider(chain)
        pool = self.pool_contracts[chain]
        checksum_address = AsyncWeb3.to_checksum_address(asset_address)

        reserve_data = await pool.functions.getReserveData(checksum_address).call()
        liquidity_rate_ray = reserve_data[2]

        current_apy = float(liquidity_rate_ray) / 1e27

        logger.debug("[AAVE][EXECUTOR][APY] Fetched APY for %s: %f", asset_address, current_apy)

        return current_apy

    async def fetch_asset_oracle_price(self, chain: BlockchainNetwork, asset_address: str) -> float:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        pool = self.pool_contracts[chain]

        provider_address = await pool.functions.ADDRESSES_PROVIDER().call()
        provider_contract = client.eth.contract(address=provider_address, abi=ADDRESS_PROVIDER_ABI)
        oracle_address = await provider_contract.functions.getPriceOracle().call()
        oracle_contract = client.eth.contract(address=oracle_address, abi=AAVE_ORACLE_ABI)

        checksum_address = AsyncWeb3.to_checksum_address(asset_address)
        raw_price = await oracle_contract.functions.getAssetPrice(checksum_address).call()

        logger.debug("[AAVE][EXECUTOR][ORACLE] Fetched price for %s: %f", asset_address, raw_price)

        return float(raw_price) / 1e8

    async def fetch_token_balance(self, chain: BlockchainNetwork, asset_address: str) -> float:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        pool = self.pool_contracts[chain]

        checksum_asset = AsyncWeb3.to_checksum_address(asset_address)
        reserve_data = await pool.functions.getReserveData(checksum_asset).call()
        token_address = reserve_data[8]

        token_contract = client.eth.contract(address=token_address, abi=ERC20_ABI)
        balance_wei = await token_contract.functions.balanceOf(self.wallet_address).call()
        decimals = await token_contract.functions.decimals().call()

        return float(balance_wei) / (10 ** decimals)

    async def get_live_metrics(
            self,
            chain: BlockchainNetwork,
            asset_in_address: str,
            asset_out_address: str
    ) -> AaveLiveMetrics:
        current_apy = await self.fetch_supply_apy(chain, asset_in_address)
        asset_out_price_usd = await self.fetch_asset_oracle_price(chain, asset_out_address)
        return AaveLiveMetrics(
            supply_apy=current_apy,
            asset_out_price_usd=asset_out_price_usd
        )

    async def verify_active_debt(self, chain: BlockchainNetwork, asset_address: str) -> bool:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        pool = self.pool_contracts[chain]

        checksum_address = AsyncWeb3.to_checksum_address(asset_address)
        try:
            reserve_data = await pool.functions.getReserveData(checksum_address).call()
            variable_debt_token_address = reserve_data[10]

            debt_contract = client.eth.contract(address=variable_debt_token_address, abi=ERC20_ABI)
            debt_balance = await debt_contract.functions.balanceOf(self.wallet_address).call()
            return debt_balance > 0
        except Exception as exception:
            logger.exception("[AAVE][EXECUTOR] Debt verification failed: %s", exception)
            return True

    async def broadcast_withdrawal(
            self,
            chain: BlockchainNetwork,
            asset_address: str,
            amount_in_wei: int,
    ) -> AaveEvmTransactionBroadcast:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        pool = self.pool_contracts[chain]

        checksum_asset = AsyncWeb3.to_checksum_address(asset_address)
        nonce: int = await self._resolve_pending_transaction_nonce(chain)

        withdraw_transaction: TxParams = await pool.functions.withdraw(
            checksum_asset, amount_in_wei, self.wallet_address
        ).build_transaction({
            'from': self.wallet_address,
            'nonce': nonce,
        })
        withdraw_transaction = await self._build_eip1559_transaction_parameters(
            chain=chain,
            transaction_parameters=withdraw_transaction,
            gas_limit=AAVE_EVM_POOL_OPERATION_GAS_LIMIT,
        )

        signed_transaction = client.eth.account.sign_transaction(withdraw_transaction, self.private_key)
        transaction_hash = await client.eth.send_raw_transaction(signed_transaction.raw_transaction)
        transaction_hash_hex = normalize_evm_transaction_hash(transaction_hash)

        logger.info("[AAVE][EXECUTOR][WITHDRAW] Transaction sent: %s nonce=%s", transaction_hash_hex, nonce)
        return AaveEvmTransactionBroadcast(
            transaction_hash=transaction_hash_hex,
            nonce=nonce,
            submitted_gas_limit=AAVE_EVM_POOL_OPERATION_GAS_LIMIT,
        )

    async def broadcast_supply(
            self,
            chain: BlockchainNetwork,
            asset_address: str,
            amount_in_wei: int,
    ) -> AaveEvmTransactionBroadcast:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        pool = self.pool_contracts[chain]

        await self.ensure_erc20_allowance(
            chain=chain,
            token_address=asset_address,
            spender_address=pool.address,
            required_amount_wei=amount_in_wei,
        )

        checksum_asset = AsyncWeb3.to_checksum_address(asset_address)
        nonce: int = await self._resolve_pending_transaction_nonce(chain)
        supply_transaction: TxParams = await pool.functions.supply(
            checksum_asset, amount_in_wei, self.wallet_address, 0
        ).build_transaction({
            'from': self.wallet_address,
            'nonce': nonce,
        })
        supply_transaction = await self._build_eip1559_transaction_parameters(
            chain=chain,
            transaction_parameters=supply_transaction,
            gas_limit=AAVE_EVM_POOL_OPERATION_GAS_LIMIT,
        )

        signed_supply = client.eth.account.sign_transaction(supply_transaction, self.private_key)
        transaction_hash = await client.eth.send_raw_transaction(signed_supply.raw_transaction)
        transaction_hash_hex = normalize_evm_transaction_hash(transaction_hash)

        logger.info("[AAVE][EXECUTOR][SUPPLY] Transaction sent: %s nonce=%s", transaction_hash_hex, nonce)
        return AaveEvmTransactionBroadcast(
            transaction_hash=transaction_hash_hex,
            nonce=nonce,
            submitted_gas_limit=AAVE_EVM_POOL_OPERATION_GAS_LIMIT,
        )

    async def fetch_erc20_balance(self, chain: BlockchainNetwork, token_address: str) -> int:
        await self._initialize_provider(chain)
        client = self.web3_clients[chain]
        checksum_address = AsyncWeb3.to_checksum_address(token_address)
        contract = client.eth.contract(address=checksum_address, abi=ERC20_ABI)
        balance = await contract.functions.balanceOf(self.wallet_address).call()
        return int(balance)

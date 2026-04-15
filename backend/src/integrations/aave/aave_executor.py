from __future__ import annotations

import asyncio
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract
from web3.types import TxParams

from src.configuration.config import settings
from src.integrations.aave.aave_abis import (
    AAVE_POOL_ABI,
    ERC20_ABI,
    ADDRESS_PROVIDER_ABI,
    AAVE_ORACLE_ABI
)
from src.integrations.aave.aave_structures import AaveLiveMetrics
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)
Account.enable_unaudited_hdwallet_features()


class AaveExecutor:
    def __init__(self) -> None:
        self._web3_clients: dict[str, AsyncWeb3] = {}
        self._pool_contracts: dict[str, AsyncContract] = {}
        self._wallet_address: str = ""
        self._private_key: str = ""

    def get_wallet_address(self) -> str:
        return self._wallet_address

    async def _initialize_provider(self, chain: str) -> None:
        if chain in self._web3_clients:
            return

        if not settings.WALLET_MNEMONIC:
            logger.error("[AAVE][EXECUTOR][INIT] Mnemonic configuration is missing")
            raise ValueError("Mnemonic configuration is missing.")

        account: LocalAccount = Account.from_mnemonic(
            settings.WALLET_MNEMONIC,
            account_path=f"m/44'/60'/0'/0/{settings.WALLET_DERIVATION_INDEX}"
        )
        self._private_key = account.key.hex()
        self._wallet_address = account.address

        if chain == "avalanche":
            rpc_url = settings.AVALANCHE_RPC_URL
            pool_address = settings.AAVE_POOL_V3_ADDRESS
        else:
            logger.error("[AAVE][EXECUTOR][INIT] Chain '%s' is not supported", chain)
            raise ValueError(f"Chain '{chain}' is not supported for Aave.")

        client = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
        self._web3_clients[chain] = client

        pool_address_checksum = AsyncWeb3.to_checksum_address(pool_address)
        self._pool_contracts[chain] = client.eth.contract(address=pool_address_checksum, abi=AAVE_POOL_ABI)

        logger.info("[AAVE][EXECUTOR][INIT] Provider initialized for chain: %s", chain)

    async def fetch_supply_apy(self, chain: str, asset_address: str) -> float:
        await self._initialize_provider(chain)
        pool = self._pool_contracts[chain]
        checksum_address = AsyncWeb3.to_checksum_address(asset_address)

        reserve_data = await pool.functions.getReserveData(checksum_address).call()
        liquidity_rate_ray = reserve_data[2]

        current_apy = float(liquidity_rate_ray) / 1e27

        logger.debug("[AAVE][EXECUTOR][APY] Fetched APY for %s: %f", asset_address, current_apy)

        return current_apy

    async def fetch_asset_oracle_price(self, chain: str, asset_address: str) -> float:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]
        pool = self._pool_contracts[chain]

        provider_address = await pool.functions.ADDRESSES_PROVIDER().call()
        provider_contract = client.eth.contract(address=provider_address, abi=ADDRESS_PROVIDER_ABI)
        oracle_address = await provider_contract.functions.getPriceOracle().call()
        oracle_contract = client.eth.contract(address=oracle_address, abi=AAVE_ORACLE_ABI)

        checksum_address = AsyncWeb3.to_checksum_address(asset_address)
        raw_price = await oracle_contract.functions.getAssetPrice(checksum_address).call()

        logger.debug("[AAVE][EXECUTOR][ORACLE] Fetched price for %s: %f", asset_address, raw_price)

        return float(raw_price) / 1e8

    async def fetch_token_balance(self, chain: str, asset_address: str) -> float:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]
        pool = self._pool_contracts[chain]

        checksum_asset = AsyncWeb3.to_checksum_address(asset_address)
        reserve_data = await pool.functions.getReserveData(checksum_asset).call()
        token_address = reserve_data[8]

        token_contract = client.eth.contract(address=token_address, abi=ERC20_ABI)
        balance_wei = await token_contract.functions.balanceOf(self._wallet_address).call()
        decimals = await token_contract.functions.decimals().call()

        return float(balance_wei) / (10 ** decimals)

    async def get_live_metrics(
            self,
            chain: str,
            asset_in_address: str,
            asset_out_address: str
    ) -> AaveLiveMetrics:
        current_apy = await self.fetch_supply_apy(chain, asset_in_address)
        asset_out_price_usd = await self.fetch_asset_oracle_price(chain, asset_out_address)
        return AaveLiveMetrics(
            supply_apy=current_apy,
            asset_out_price_usd=asset_out_price_usd
        )

    async def verify_active_debt(self, chain: str, asset_address: str) -> bool:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]
        pool = self._pool_contracts[chain]

        checksum_address = AsyncWeb3.to_checksum_address(asset_address)
        try:
            reserve_data = await pool.functions.getReserveData(checksum_address).call()
            variable_debt_token_address = reserve_data[10]

            debt_contract = client.eth.contract(address=variable_debt_token_address, abi=ERC20_ABI)
            debt_balance = await debt_contract.functions.balanceOf(self._wallet_address).call()
            return debt_balance > 0
        except Exception as exception:
            logger.exception("[AAVE][EXECUTOR] Debt verification failed: %s", exception)
            return True

    async def execute_withdrawal(self, chain: str, asset_address: str, amount_in_wei: int) -> Optional[str]:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]
        pool = self._pool_contracts[chain]

        checksum_asset = AsyncWeb3.to_checksum_address(asset_address)
        try:
            nonce = await client.eth.get_transaction_count(self._wallet_address)
            gas_price = await client.eth.gas_price
            adjusted_gas_price = int(gas_price * 1.1)

            withdraw_transaction: TxParams = await pool.functions.withdraw(
                checksum_asset, amount_in_wei, self._wallet_address
            ).build_transaction({
                'from': self._wallet_address,
                'nonce': nonce,
                'gas': 350000,
                'gasPrice': adjusted_gas_price
            })

            signed_transaction = client.eth.account.sign_transaction(withdraw_transaction, self._private_key)
            transaction_hash = await client.eth.send_raw_transaction(signed_transaction.rawTransaction)

            logger.info("[AAVE][EXECUTOR][WITHDRAW] Transaction sent: %s", transaction_hash.hex())
            return transaction_hash.hex()
        except Exception as exception:
            logger.exception("[AAVE][EXECUTOR][WITHDRAW] Withdrawal execution failed: %s", exception)
            return None

    async def execute_supply(self, chain: str, asset_address: str, amount_in_wei: int) -> Optional[str]:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]
        pool = self._pool_contracts[chain]

        checksum_asset = AsyncWeb3.to_checksum_address(asset_address)
        try:
            token_contract = client.eth.contract(address=checksum_asset, abi=ERC20_ABI)
            nonce = await client.eth.get_transaction_count(self._wallet_address)
            gas_price = await client.eth.gas_price
            adjusted_gas_price = int(gas_price * 1.1)

            allowance = await token_contract.functions.allowance(self._wallet_address, pool.address).call()
            if allowance < amount_in_wei:
                approve_transaction: TxParams = await token_contract.functions.approve(
                    pool.address, amount_in_wei
                ).build_transaction({
                    'from': self._wallet_address, 'nonce': nonce,
                    'gas': 80000, 'gasPrice': adjusted_gas_price
                })
                signed_approval = client.eth.account.sign_transaction(approve_transaction, self._private_key)
                await client.eth.send_raw_transaction(signed_approval.rawTransaction)
                nonce += 1
                await asyncio.sleep(3)

            supply_transaction: TxParams = await pool.functions.supply(
                checksum_asset, amount_in_wei, self._wallet_address, 0
            ).build_transaction({
                'from': self._wallet_address, 'nonce': nonce,
                'gas': 350000, 'gasPrice': adjusted_gas_price
            })

            signed_supply = client.eth.account.sign_transaction(supply_transaction, self._private_key)
            transaction_hash = await client.eth.send_raw_transaction(signed_supply.rawTransaction)
            return transaction_hash.hex()
        except Exception as exception:
            logger.exception("[AAVE][EXECUTOR] Supply execution failed: %s", exception)
            return None

    async def approve_and_execute_raw_transaction(
            self, chain: str, source_token: str, spender: str, amount_in_wei: int,
            to_address: str, tx_data: str, tx_value: int, gas_limit: int, chain_id_numeric: int
    ) -> Optional[str]:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]

        checksum_token = AsyncWeb3.to_checksum_address(source_token)
        checksum_spender = AsyncWeb3.to_checksum_address(spender)
        checksum_to = AsyncWeb3.to_checksum_address(to_address)

        try:
            token_contract = client.eth.contract(address=checksum_token, abi=ERC20_ABI)
            nonce = await client.eth.get_transaction_count(self._wallet_address)
            gas_price = await client.eth.gas_price

            allowance = await token_contract.functions.allowance(self._wallet_address, checksum_spender).call()
            if allowance < amount_in_wei:
                approve_transaction: TxParams = await token_contract.functions.approve(
                    checksum_spender, amount_in_wei
                ).build_transaction({
                    'from': self._wallet_address, 'nonce': nonce,
                    'gas': 80000, 'gasPrice': gas_price
                })
                signed_approval = client.eth.account.sign_transaction(approve_transaction, self._private_key)
                await client.eth.send_raw_transaction(signed_approval.rawTransaction)
                nonce += 1
                await asyncio.sleep(3)

            raw_transaction: TxParams = {
                'from': self._wallet_address,
                'to': checksum_to,
                'data': tx_data,
                'value': tx_value,
                'nonce': nonce,
                'gas': int(gas_limit * 1.2),
                'gasPrice': gas_price,
                'chainId': chain_id_numeric
            }
            signed_tx = client.eth.account.sign_transaction(raw_transaction, self._private_key)
            transaction_hash = await client.eth.send_raw_transaction(signed_tx.rawTransaction)
            return transaction_hash.hex()
        except Exception as exception:
            logger.exception("[ONCHAIN][EXECUTOR] Raw transaction failed: %s", exception)
            return None

    async def fetch_erc20_balance(self, chain: str, token_address: str) -> int:
        await self._initialize_provider(chain)
        client = self._web3_clients[chain]
        checksum_address = AsyncWeb3.to_checksum_address(token_address)
        contract = client.eth.contract(address=checksum_address, abi=ERC20_ABI)
        balance = await contract.functions.balanceOf(self._wallet_address).call()
        return int(balance)

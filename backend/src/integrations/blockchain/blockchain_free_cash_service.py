from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_utils import get_currency_symbol
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class BlockchainCashBalance(BaseModel):
    blockchain_network: BlockchainNetwork
    stablecoin_symbol: str
    stablecoin_address: str
    stablecoin_currency_symbol: str
    balance_raw: float
    native_token_symbol: str
    native_token_balance_raw: float
    native_token_balance_usd: float


def _get_native_token_symbol_for_blockchain(blockchain: BlockchainNetwork) -> str:
    mapping = {
        BlockchainNetwork.SOLANA: "SOL",
        BlockchainNetwork.BSC: "BNB",
        BlockchainNetwork.BASE: "ETH",
        BlockchainNetwork.AVALANCHE: "AVAX",
    }
    if blockchain not in mapping:
        raise ValueError(f"No native token symbol configured for blockchain {blockchain.value}")
    return mapping[blockchain]


def _get_stablecoin_address_for_blockchain(blockchain: BlockchainNetwork) -> str:
    setting_name = f"TRADING_STABLECOIN_ADDRESS_{blockchain.name}"
    return getattr(settings, setting_name, "")


def _fetch_solana_stablecoin_balance(rpc_url: str, wallet_address: str, token_mint: str) -> float:
    import requests

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": token_mint},
            {"encoding": "jsonParsed"},
        ],
    }

    response = requests.post(rpc_url, json=payload, timeout=10, headers={"Content-Type": "application/json"})
    if response.status_code == 429:
        raise ConnectionError(f"HTTP 429 Rate limit from {rpc_url}")

    response_data = response.json()

    if "error" in response_data:
        error_data = response_data["error"]
        if isinstance(error_data, dict) and error_data.get("code") == 429:
            raise ConnectionError(f"JSON-RPC 429 Rate limit from {rpc_url}")
        logger.warning("[BLOCKCHAIN][FREE_CASH][SOLANA] RPC error for wallet=%s token=%s — %s", wallet_address, token_mint, error_data)
        return 0.0

    token_accounts = response_data.get("result", {}).get("value", [])
    if not token_accounts:
        return 0.0

    token_account_info = token_accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
    balance_raw = int(token_account_info.get("tokenAmount", {}).get("amount", "0"))
    decimals = int(token_account_info.get("tokenAmount", {}).get("decimals", 6))

    return float(balance_raw) / (10 ** decimals)


def _fetch_solana_native_balance(rpc_url: str, wallet_address: str) -> float:
    import requests

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [
            wallet_address
        ],
    }

    response = requests.post(rpc_url, json=payload, timeout=10, headers={"Content-Type": "application/json"})
    if response.status_code == 429:
        raise ConnectionError(f"HTTP 429 Rate limit from {rpc_url}")

    response_data = response.json()

    if "error" in response_data:
        error_data = response_data["error"]
        if isinstance(error_data, dict) and error_data.get("code") == 429:
            raise ConnectionError(f"JSON-RPC 429 Rate limit from {rpc_url}")
        logger.warning("[BLOCKCHAIN][FREE_CASH][SOLANA] RPC error for native balance wallet=%s — %s", wallet_address, error_data)
        return 0.0

    lamports = response_data.get("result", {}).get("value", 0)
    return float(lamports) / 10 ** 9


def _fetch_evm_stablecoin_balance(rpc_url: str, wallet_address: str, token_address: str) -> float:
    from web3 import Web3

    web3_client = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))

    erc20_abi = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "type": "function",
        },
    ]

    token_contract = web3_client.eth.contract(address=Web3.to_checksum_address(token_address), abi=erc20_abi)
    balance_wei = token_contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
    decimals = token_contract.functions.decimals().call()

    return float(balance_wei) / (10 ** decimals)


def _fetch_evm_native_balance(rpc_url: str, wallet_address: str) -> float:
    from web3 import Web3

    web3_client = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    balance_wei = web3_client.eth.get_balance(Web3.to_checksum_address(wallet_address))
    return float(balance_wei) / 10 ** 18


def _resolve_blockchain_network(chain: str) -> Optional[BlockchainNetwork]:
    if not chain:
        return None
    normalized = chain.strip().lower()
    for member in BlockchainNetwork:
        if member.value == normalized:
            return member
    logger.debug("[BLOCKCHAIN][FREE_CASH] Unknown blockchain network requested: %s", chain)
    return None


def _get_wallet_address_for_blockchain(blockchain: BlockchainNetwork) -> str:
    if blockchain == BlockchainNetwork.SOLANA:
        try:
            from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
            solana_signer = build_default_solana_signer()
            return solana_signer.address
        except ConnectionError:
            raise
        except Exception as exception:
            logger.exception("[BLOCKCHAIN][FREE_CASH] Solana signer unavailable — %s", exception)
            return ""

    from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer
    try:
        evm_signer = build_default_evm_signer(chain=blockchain)
        return evm_signer.wallet_address
    except ConnectionError:
        raise
    except Exception as exception:
        logger.exception("[BLOCKCHAIN][FREE_CASH] EVM signer unavailable for %s — %s", blockchain, exception)
        return ""


def fetch_stablecoin_balance_for_blockchain(blockchain: BlockchainNetwork) -> BlockchainCashBalance:
    stablecoin_address = _get_stablecoin_address_for_blockchain(blockchain)
    native_token_symbol = _get_native_token_symbol_for_blockchain(blockchain)

    if not stablecoin_address:
        logger.debug("[BLOCKCHAIN][FREE_CASH] No stablecoin address configured for %s", blockchain.value)
        return BlockchainCashBalance(
            blockchain_network=blockchain,
            stablecoin_symbol=settings.TRADING_STABLECOIN_SYMBOL,
            stablecoin_address="",
            stablecoin_currency_symbol=get_currency_symbol(settings.TRADING_STABLECOIN_SYMBOL),
            balance_raw=0.0,
            native_token_symbol=native_token_symbol,
            native_token_balance_raw=0.0,
            native_token_balance_usd=0.0,
        )

    wallet_address = _get_wallet_address_for_blockchain(blockchain)
    if not wallet_address:
        logger.debug("[BLOCKCHAIN][FREE_CASH] Wallet unavailable for %s", blockchain.value)
        return BlockchainCashBalance(
            blockchain_network=blockchain,
            stablecoin_symbol=settings.TRADING_STABLECOIN_SYMBOL,
            stablecoin_address=stablecoin_address,
            stablecoin_currency_symbol=get_currency_symbol(settings.TRADING_STABLECOIN_SYMBOL),
            balance_raw=0.0,
            native_token_symbol=native_token_symbol,
            native_token_balance_raw=0.0,
            native_token_balance_usd=0.0,
        )

    balance_raw = 0.0
    native_token_balance_raw = 0.0
    native_token_balance_usd = 0.0

    max_retries = 3
    fetch_succeeded = False
    last_connection_error: ConnectionError | None = None

    for attempt in range(max_retries):
        try:
            try:
                rpc_url = resolve_rpc_url_for_chain(blockchain)
            except ConnectionError as exception:
                logger.warning("[BLOCKCHAIN][FREE_CASH] No reachable RPC for chain %s — %s", blockchain.value, exception)
                raise

            if blockchain == BlockchainNetwork.SOLANA:
                balance_raw = _fetch_solana_stablecoin_balance(rpc_url, wallet_address, stablecoin_address)
                native_token_balance_raw = _fetch_solana_native_balance(rpc_url, wallet_address)
            else:
                balance_raw = _fetch_evm_stablecoin_balance(rpc_url, wallet_address, stablecoin_address)
                native_token_balance_raw = _fetch_evm_native_balance(rpc_url, wallet_address)

            fetch_succeeded = True
            break
        except ConnectionError as exception:
            from src.integrations.blockchain.blockchain_rpc_registry import invalidate_rpc_cache_for_chain
            invalidate_rpc_cache_for_chain(blockchain)
            last_connection_error = exception
            logger.warning("[BLOCKCHAIN][FREE_CASH] RPC failure (%s), retrying %d/%d...", exception, attempt + 1, max_retries)
        except Exception as exception:
            from src.integrations.blockchain.blockchain_rpc_registry import invalidate_rpc_cache_for_chain
            invalidate_rpc_cache_for_chain(blockchain)
            logger.warning("[BLOCKCHAIN][FREE_CASH] Unexpected RPC error (%s), retrying %d/%d...", type(exception).__name__, attempt + 1, max_retries)

    if not fetch_succeeded:
        raise last_connection_error or ConnectionError(
            f"[BLOCKCHAIN][FREE_CASH] Exhausted RPC retries for chain {blockchain.value}"
        )

    logger.info(
        "[BLOCKCHAIN][FREE_CASH] Balance for %s on %s = %.6f USDT | Gas = %.4f %s (wallet=%s, token=%s)",
        settings.TRADING_STABLECOIN_SYMBOL, blockchain.value, balance_raw, native_token_balance_raw, native_token_symbol, wallet_address, stablecoin_address,
    )

    try:
        native_token_price_usd: float | None = None
        if blockchain == BlockchainNetwork.SOLANA:
            from src.integrations.blockchain.solana.solana_rpc_client import resolve_sol_usd_price
            native_token_price_usd = resolve_sol_usd_price(rpc_url)
        else:
            from src.integrations.blockchain.blockchain_rpc_registry import resolve_web3_provider_for_chain
            from src.integrations.blockchain.evm.blockchain_evm_price_reader import read_evm_native_token_price_usd
            web3_provider = resolve_web3_provider_for_chain(blockchain)
            if web3_provider is not None:
                native_token_price_usd = read_evm_native_token_price_usd(web3_provider, blockchain)

        if native_token_price_usd is not None and native_token_price_usd > 0.0:
            native_token_balance_usd = native_token_balance_raw * native_token_price_usd
    except Exception:
        logger.exception(
            "[BLOCKCHAIN][FREE_CASH] Failed to resolve native token USD equivalent for %s",
            blockchain.value,
        )

    return BlockchainCashBalance(
        blockchain_network=blockchain,
        stablecoin_symbol=settings.TRADING_STABLECOIN_SYMBOL,
        stablecoin_address=stablecoin_address,
        stablecoin_currency_symbol=get_currency_symbol(settings.TRADING_STABLECOIN_SYMBOL),
        balance_raw=round(balance_raw, 6),
        native_token_symbol=native_token_symbol,
        native_token_balance_raw=round(native_token_balance_raw, 6),
        native_token_balance_usd=round(native_token_balance_usd, 4),
    )


def fetch_stablecoin_balances_for_allowed_chains() -> list[BlockchainCashBalance]:
    if settings.PAPER_MODE:
        logger.debug("[BLOCKCHAIN][FREE_CASH] Paper mode active — skipping on-chain balance fetch")
        return []

    allowed_chains = settings.TRADING_ALLOWED_CHAINS
    if not allowed_chains:
        return []

    balances: list[BlockchainCashBalance] = []
    for chain in allowed_chains:
        blockchain = _resolve_blockchain_network(chain)
        if not blockchain:
            continue
        balance = fetch_stablecoin_balance_for_blockchain(blockchain)
        balances.append(balance)

    return balances

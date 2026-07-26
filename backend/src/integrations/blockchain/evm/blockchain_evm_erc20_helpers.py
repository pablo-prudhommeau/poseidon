from __future__ import annotations

from web3 import Web3

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer
from src.integrations.lifi.lifi_helpers import LIFI_EVM_DIAMOND_CONTRACT_ADDRESS
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

ERC20_ABI: list[dict[str, object]] = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

EVM_APPROVE_GAS_LIMIT: int = 100_000


def resolve_evm_erc20_decimals(blockchain_network: BlockchainNetwork, token_address: str) -> int:
    signer = build_default_evm_signer(blockchain_network)
    token_contract = signer.web3_provider.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )
    return int(token_contract.functions.decimals().call())


def resolve_evm_erc20_balance_raw(
        blockchain_network: BlockchainNetwork,
        token_address: str,
) -> int:
    signer = build_default_evm_signer(blockchain_network)
    token_contract = signer.web3_provider.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )
    return int(token_contract.functions.balanceOf(signer.wallet_address).call())


def ensure_evm_erc20_allowance_for_lifi_diamond(
        blockchain_network: BlockchainNetwork,
        token_address: str,
        required_amount_wei: int,
) -> None:
    signer = build_default_evm_signer(blockchain_network)
    checksum_token = Web3.to_checksum_address(token_address)
    checksum_spender = Web3.to_checksum_address(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS)
    token_contract = signer.web3_provider.eth.contract(address=checksum_token, abi=ERC20_ABI)

    current_allowance = int(token_contract.functions.allowance(signer.wallet_address, checksum_spender).call())
    if current_allowance >= required_amount_wei:
        logger.debug(
            "[BLOCKCHAIN][EVM][ERC20][ALLOWANCE] Sufficient allowance — blockchain_network=%s token=%s "
            "allowance_wei=%d required_wei=%d",
            blockchain_network.value,
            checksum_token,
            current_allowance,
            required_amount_wei,
        )
        return

    logger.info(
        "[BLOCKCHAIN][EVM][ERC20][ALLOWANCE] Approving LiFi diamond — blockchain_network=%s token=%s required_wei=%d",
        blockchain_network.value,
        checksum_token,
        required_amount_wei,
    )
    maximum_allowance_wei = (2**256) - 1
    approval_transaction_hash = signer.broadcast_transaction(
        recipient_address=checksum_token,
        transaction_data_hex=token_contract.encode_abi(
            abi_element_identifier="approve",
            args=[checksum_spender, maximum_allowance_wei],
        ),
        value_in_wei=0,
        gas_limit=EVM_APPROVE_GAS_LIMIT,
    )
    if not signer.confirm_transaction(approval_transaction_hash):
        raise RuntimeError(
            f"ERC20 allowance approval failed for token {checksum_token} on {blockchain_network.value}",
        )

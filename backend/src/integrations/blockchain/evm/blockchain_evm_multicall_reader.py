from __future__ import annotations

from typing import Final, Optional

from eth_typing import ChecksumAddress
from pydantic import BaseModel
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

AVALANCHE_MULTICALL3_CONTRACT_ADDRESS: Final[str] = "0xcA11bde05977b3631167028862bE2a173976CA11"

MULTICALL3_ABI: Final[list[dict[str, object]]] = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "target", "type": "address"},
                    {"internalType": "bool", "name": "allowFailure", "type": "bool"},
                    {"internalType": "bytes", "name": "callData", "type": "bytes"},
                ],
                "internalType": "struct Multicall3.Call3[]",
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate3",
        "outputs": [
            {
                "components": [
                    {"internalType": "bool", "name": "success", "type": "bool"},
                    {"internalType": "bytes", "name": "returnData", "type": "bytes"},
                ],
                "internalType": "struct Multicall3.Result[]",
                "name": "returnData",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "payable",
        "type": "function",
    },
]


class BlockchainEvmMulticallCall(BaseModel):
    target_address: str
    call_data: bytes
    allow_failure: bool = True


class BlockchainEvmMulticallResult(BaseModel):
    is_success: bool
    return_data: bytes


def build_multicall3_contract(web3_client: AsyncWeb3) -> AsyncContract:
    checksum_multicall_address: ChecksumAddress = AsyncWeb3.to_checksum_address(
        AVALANCHE_MULTICALL3_CONTRACT_ADDRESS,
    )
    return web3_client.eth.contract(
        address=checksum_multicall_address,
        abi=MULTICALL3_ABI,
    )


async def execute_multicall3_aggregate(
        web3_client: AsyncWeb3,
        multicall_calls: list[BlockchainEvmMulticallCall],
        block_number: Optional[int] = None,
) -> list[BlockchainEvmMulticallResult]:
    if len(multicall_calls) == 0:
        return []

    multicall_contract = build_multicall3_contract(web3_client=web3_client)
    encoded_calls: list[tuple[ChecksumAddress, bool, bytes]] = [
        (
            AsyncWeb3.to_checksum_address(multicall_call.target_address),
            multicall_call.allow_failure,
            multicall_call.call_data,
        )
        for multicall_call in multicall_calls
    ]
    if block_number is None:
        raw_results = await multicall_contract.functions.aggregate3(encoded_calls).call()
    else:
        raw_results = await multicall_contract.functions.aggregate3(encoded_calls).call(
            block_identifier=block_number,
        )
    multicall_results: list[BlockchainEvmMulticallResult] = [
        BlockchainEvmMulticallResult(
            is_success=bool(raw_result[0]),
            return_data=bytes(raw_result[1]),
        )
        for raw_result in raw_results
    ]
    return multicall_results

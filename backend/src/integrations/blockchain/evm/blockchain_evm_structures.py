from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.core.structures.structures import BlockchainNetwork


class EvmPoolPriceInQuote(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    price_in_quote_token: float
    quote_token_address: str


class EvmChainPriceMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    blockchain_network: BlockchainNetwork
    stablecoin_addresses: frozenset[str]
    native_wrapped_token_address: str
    native_token_reference_stablecoin_pair_address: str
    uniswap_v4_state_view_contract_address: Optional[str] = None
    uniswap_v4_position_manager_contract_address: Optional[str] = None


class EvmChainPriceMetadataRegistry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    entries: tuple[EvmChainPriceMetadata, ...]

    def resolve(self, blockchain_network: BlockchainNetwork) -> EvmChainPriceMetadata:
        for chain_price_metadata in self.entries:
            if chain_price_metadata.blockchain_network == blockchain_network:
                return chain_price_metadata
        raise ValueError(
            f"No EVM chain price metadata registered for blockchain '{blockchain_network.value}'",
        )


EVM_CHAIN_PRICE_METADATA_REGISTRY = EvmChainPriceMetadataRegistry(
    entries=(
        EvmChainPriceMetadata(
            blockchain_network=BlockchainNetwork.BSC,
            stablecoin_addresses=frozenset(
                {
                    "0x55d398326f99059ff775485246999027b3197955",
                    "0xe9e7cea3dedca5984780bafc599bd69add087d56",
                    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
                },
            ),
            native_wrapped_token_address="0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
            native_token_reference_stablecoin_pair_address="0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
        ),
        EvmChainPriceMetadata(
            blockchain_network=BlockchainNetwork.BASE,
            stablecoin_addresses=frozenset(
                {
                    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
                },
            ),
            native_wrapped_token_address="0x4200000000000000000000000000000000000006",
            native_token_reference_stablecoin_pair_address="0xd0b53d9277642d899df5c87a3966a349a798f224",
        ),
        EvmChainPriceMetadata(
            blockchain_network=BlockchainNetwork.ROBINHOOD,
            stablecoin_addresses=frozenset(
                {
                    "0x5fc5360d0400a0fd4f2af552add042d716f1d168",
                },
            ),
            native_wrapped_token_address="0x0bd7d308f8e1639fab988df18a8011f41eacad73",
            native_token_reference_stablecoin_pair_address="0x69bfaf19c9f377bb306a89aed9f6b07e2c1a8d9a",
            uniswap_v4_state_view_contract_address="0xF3334192D15450CdD385c8B70e03f9A6bD9E673b",
            uniswap_v4_position_manager_contract_address="0x58daec3116aae6D93017bAAea7749052E8a04fA7",
        ),
    ),
)

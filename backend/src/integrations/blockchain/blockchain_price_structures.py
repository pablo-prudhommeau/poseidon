from __future__ import annotations

from pydantic import BaseModel

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_exceptions import BlockchainPriceUnavailableError


class PairAddressOnchainPrice(BaseModel):
    pair_address: str
    price_usd: float


class OnchainPricesByPairAddress(BaseModel):
    pair_address_prices: list[PairAddressOnchainPrice]

    @classmethod
    def empty(cls) -> OnchainPricesByPairAddress:
        return cls(pair_address_prices=[])

    def entry_count(self) -> int:
        return len(self.pair_address_prices)

    def merge_with(self, other: OnchainPricesByPairAddress) -> OnchainPricesByPairAddress:
        merged_by_pair_address: dict[str, PairAddressOnchainPrice] = {
            pair_address_price.pair_address: pair_address_price
            for pair_address_price in self.pair_address_prices
        }
        for pair_address_price in other.pair_address_prices:
            merged_by_pair_address[pair_address_price.pair_address] = pair_address_price
        return OnchainPricesByPairAddress(
            pair_address_prices=list(merged_by_pair_address.values()),
        )

    def resolve_price_usd_for_pair_address(
            self,
            pair_address: str,
            *,
            blockchain_network: BlockchainNetwork,
    ) -> float:
        for pair_address_price in self.pair_address_prices:
            if pair_address_price.pair_address == pair_address:
                if pair_address_price.price_usd <= 0.0:
                    raise BlockchainPriceUnavailableError(
                        f"[BLOCKCHAIN][PRICE][SERVICE] Non-positive on-chain price for pair {pair_address[:12]}",
                        blockchain_network=blockchain_network,
                    )
                return pair_address_price.price_usd
        raise BlockchainPriceUnavailableError(
            f"[BLOCKCHAIN][PRICE][SERVICE] Missing on-chain price for pair {pair_address[:12]}",
            blockchain_network=blockchain_network,
        )

    def try_resolve_price_usd_for_pair_address(self, pair_address: str) -> float | None:
        for pair_address_price in self.pair_address_prices:
            if pair_address_price.pair_address == pair_address:
                if pair_address_price.price_usd <= 0.0:
                    return None
                return pair_address_price.price_usd
        return None


class OnchainPricesFetchResult(BaseModel):
    onchain_prices: OnchainPricesByPairAddress
    had_infrastructure_failure: bool

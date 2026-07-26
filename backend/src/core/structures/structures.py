from enum import Enum

from pydantic import BaseModel

from src.core.utils.format_utils import tail


class BlockchainNetwork(str, Enum):
    PAPER = "paper"
    SOLANA = "solana"
    BSC = "bsc"
    BASE = "base"
    AVALANCHE = "avalanche"
    ROBINHOOD = "robinhood"


class Token(BaseModel):
    symbol: str
    chain: BlockchainNetwork
    token_address: str
    pair_address: str
    dex_id: str

    def __str__(self) -> str:
        return (f"[symbol={self.symbol} "
                f"chain={self.chain.value} "
                f"dex_id={self.dex_id} "
                f"token_address={tail(self.token_address)} "
                f"pair_address=…{tail(self.pair_address)}]")

    def __hash__(self) -> int:
        return hash((self.chain, self.dex_id, self.symbol, self.token_address, self.pair_address))


class Mode(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"

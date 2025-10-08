from dataclasses import dataclass
from typing import Mapping


class LifiAction:
    """Subset of the LI.FI `action` object we read for logging."""
    type: str


class LifiEstimate:
    """Subset of the LI.FI `estimate` object we read for logging."""
    tool: str


class LifiQuoteJson:
    """
    Minimal typed view over LI.FI quote JSON.

    We preserve the full raw shape but provide a typed surface for the fields
    we actually consume. Unknown fields remain available for callers as needed.
    """
    type: str
    tool: str
    action: LifiAction
    estimate: LifiEstimate
    transactionRequest: Mapping[str, object]


@dataclass(frozen=True)
class EvmChain:
    """
    Canonical mapping entry for an EVM chain supported by Dexscreener and LI.FI.

    Attributes:
        dexscreener_key: Lowercase identifier as provided by Dexscreener.
        chain_id: The LI.FI numeric chain identifier (EVM chainId).
        native_symbol: The native asset symbol for display/logging purposes.
    """
    dexscreener_key: str
    chain_id: int
    native_symbol: str

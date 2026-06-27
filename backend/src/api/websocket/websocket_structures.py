from enum import Enum
from typing import Optional

from pydantic import BaseModel


class WebsocketInboundMessage(BaseModel):
    type: str
    payload: Optional[dict] = None


class WebsocketMessageType(str, Enum):
    INITIALIZATION = "initialization"
    TRADING_PORTFOLIO = "trading_portfolio"
    TRADING_LIQUIDITY = "trading_liquidity"
    TRADING_SHADOWING_REGIME = "trading_shadowing_regime"
    TRADING_SHADOWING_VERDICT_CHRONICLE = "trading_shadowing_verdict_chronicle"
    TRADING_POSITIONS = "trading_positions"
    TRADING_POSITION_PRICES = "trading_position_prices"
    TRADING_TRADES = "trading_trades"
    AAVE_DCA_STRATEGIES = "aave_dca_strategies"
    PONG = "pong"
    ERROR = "error"
    REFRESH = "refresh"
    PING = "ping"

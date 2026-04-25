from __future__ import annotations

import statistics
from typing import List, Optional

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingThresholds
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingRiskManager:
    def __init__(self) -> None:
        self.tp1_exit_fraction_default = settings.TRADING_TP1_EXIT_FRACTION
        self.tp2_exit_fraction_default = settings.TRADING_TP2_EXIT_FRACTION
        self.stop_loss_fraction_floor = settings.TRADING_STOP_LOSS_FRACTION_FLOOR
        self.stop_loss_fraction_cap = settings.TRADING_STOP_LOSS_FRACTION_CAP
        self.stop_loss_volatility_multiplier = settings.TRADING_RISK_STOP_LOSS_VOLATILITY_MULTIPLIER
        self.default_volatility_fraction: float = 0.08
        self.target_position_volatility_fraction: float = 0.10

    def _estimate_atr_like_volatility(self, candidate: TradingCandidate) -> Optional[float]:
        token_information = candidate.dexscreener_token_information
        pct_5m = token_information.price_change.m5
        pct_1h = token_information.price_change.h1
        pct_6h = token_information.price_change.h6
        pct_24h = token_information.price_change.h24

        window: List[float] = []
        if isinstance(pct_5m, (int, float)):
            window.append(abs(pct_5m) / 100.0)
        if isinstance(pct_1h, (int, float)):
            window.append(abs(pct_1h) / 100.0)
        if isinstance(pct_6h, (int, float)):
            window.append(abs(pct_6h) / 100.0)
        if isinstance(pct_24h, (int, float)):
            window.append(abs(pct_24h) / 100.0)

        if not window:
            return None

        return max(0.01, min(0.30, statistics.fmean(window)))

    def compute_thresholds(self, entry_price: float, candidate: TradingCandidate, shadow_tp_multiplier: float = 1.0) -> TradingThresholds:
        if entry_price is None or entry_price <= 0.0:
            raise ValueError("entry_price must be > 0")

        volatility = self._estimate_atr_like_volatility(candidate) or self.default_volatility_fraction

        take_profit_one_fraction = self.tp1_exit_fraction_default * shadow_tp_multiplier
        take_profit_two_fraction = self.tp2_exit_fraction_default * shadow_tp_multiplier

        stop_loss_fraction = min(self.stop_loss_fraction_cap, max(self.stop_loss_fraction_floor, self.stop_loss_volatility_multiplier * volatility))

        if shadow_tp_multiplier >= 1.2:
            logger.info("[TRADING][RISK] Shadow TP multiplier %.2fx detected — expanding Take Profits", shadow_tp_multiplier)
        elif shadow_tp_multiplier <= 0.8:
            logger.info("[TRADING][RISK] Shadow TP multiplier %.2fx detected — tightening Take Profits", shadow_tp_multiplier)

        tp1 = entry_price * (1.0 + take_profit_one_fraction)
        tp2 = entry_price * (1.0 + take_profit_two_fraction)
        stop = entry_price * (1.0 - stop_loss_fraction)

        logger.info("[TRADING][RISK][THRESHOLDS] entry=%.10f vol≈%.3f tp1=%.6f tp2=%.6f stop=%.6f", entry_price, volatility, tp1, tp2, stop)
        logger.debug(
            "[TRADING][RISK][THRESHOLDS] stop_frac=%.3f tp1_frac=%.3f tp2_frac=%.3f (shadow_tp_mult=%.2f)",
            stop_loss_fraction, take_profit_one_fraction, take_profit_two_fraction, shadow_tp_multiplier,
        )
        return TradingThresholds(take_profit_tier_1_price=tp1, take_profit_tier_2_price=tp2, stop_loss_price=stop)

    def post_tp1_adjustments(self, entry_price: float, current_stop: float, tp1_price: float) -> float:
        if entry_price is None or entry_price <= 0.0:
            raise ValueError("entry_price must be > 0")
        if current_stop is None or current_stop <= 0.0:
            raise ValueError("current_stop must be > 0")
        if tp1_price is None or tp1_price <= 0.0:
            raise ValueError("tp1_price must be > 0")

        buffer_target = entry_price + 0.002 * entry_price
        cushion = max(0.0, 0.35 * (tp1_price - entry_price))
        new_stop = max(current_stop, buffer_target + cushion)

        logger.info("[TRADING][RISK][AFTER_TP1] stop: %.6f → %.6f", current_stop, new_stop)
        return new_stop

    def size_multiplier(self, candidate: TradingCandidate) -> float:
        volatility = self._estimate_atr_like_volatility(candidate) or self.default_volatility_fraction
        target = self.target_position_volatility_fraction

        if target <= 0.0:
            logger.debug("[TRADING][RISK][SIZING] target_position_volatility_fraction <= 0; using 1.0")
            return 1.0

        multiplier = max(0.5, min(1.0, target / max(volatility, 1e-9)))
        logger.debug("[TRADING][RISK][SIZING] vol≈%.3f → size_mult=%.2f", volatility, multiplier)
        return multiplier

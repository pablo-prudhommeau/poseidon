from __future__ import annotations

from typing import List, Optional

from src.api.websocket.telemetry import TelemetryService
from src.configuration.config import settings, _to_dict
from src.core.ai.chart_signal_provider import ChartAiSignalProvider
from src.core.gates.risk_manager import AdaptiveRiskManager
from src.core.gates.trader import Trader
from src.core.gates.trending_scoring import ScoringEngine
from src.core.onchain.evm_signer import build_default_evm_signer
from src.core.onchain.solana_signer import build_default_solana_signer
from src.core.structures.structures import Candidate, OrderPayload, LifiRoute, Token
from src.core.utils.date_utils import timezone_now
from src.integrations.lifi.lifi_client import build_native_to_token_route, resolve_lifi_chain_id
from src.logging.logger import get_logger
from src.persistence.dao.portfolio_snapshots import get_portfolio_snapshot
from src.persistence.db import _session

log = get_logger(__name__)


class AnalyticsRecorder:
    """
    Small helper around :class:`TelemetryService` to ensure strict payloads,
    consistent tagging and clear intent logging.
    """

    @staticmethod
    def persist_and_broadcast(
            candidate: Candidate,
            *,
            rank: int,
            decision: str,
            reason: str,
            sizing_multiplier: float = 0.0,
            order_notional_usd: float = 0.0,
            free_cash_before_usd: float = 0.0,
            free_cash_after_usd: float = 0.0,
    ) -> None:
        """
        Persist an analytics event and broadcast it over WebSocket.
        """
        from src.persistence.models import Analytics

        final_score = candidate.entry_score if candidate.score_final <= 0 else candidate.score_final

        token_information = candidate.dexscreener_token_information
        base_token = token_information.base_token
        payload = Analytics(
            symbol=base_token.symbol.upper(),
            chain=str(token_information.chain_id),
            tokenAddress=str(base_token.address),
            pairAddress=str(token_information.pair_address),
            priceUsd=float(token_information.price_usd),
            priceNative=float(token_information.price_native),
            rank=int(rank),
            quality_score=float(candidate.quality_score),
            statistics_score=float(candidate.statistics_score),
            entry_score=float(candidate.entry_score),
            final_score=float(final_score),
            ai_probability_tp1_before_sl=float(candidate.ai_buy_probability),
            ai_quality_score_delta=float(candidate.ai_quality_delta),
            token_age_hours=float(token_information.age_hours),
            volume5m_usd=float(token_information.volume.m5),
            volume1h_usd=float(token_information.volume.h1),
            volume6h_usd=float(token_information.volume.h6),
            volume24h_usd=float(token_information.volume.h24),
            liquidity_usd=float(token_information.liquidity.usd),
            pct_5m=float(token_information.price_change.m5),
            pct_1h=float(token_information.price_change.h1),
            pct_6h=float(token_information.price_change.h6),
            pct_24h=float(token_information.price_change.h24),
            tx_5m=int(token_information.txns.m5.total),
            tx_1h=int(token_information.txns.h1.total),
            tx_6h=int(token_information.txns.h6.total),
            tx_24h=int(token_information.txns.h24.total),
            evaluated_at=timezone_now(),
            decision=decision.upper(),
            decision_reason=reason,
            sizing_multiplier=float(sizing_multiplier or 0.0),
            order_notional_usd=float(order_notional_usd or 0.0),
            free_cash_before_usd=float(free_cash_before_usd or 0.0),
            free_cash_after_usd=float(free_cash_after_usd or 0.0),
            raw_dexscreener=token_information.to_dict(),
            raw_settings=_to_dict(settings)
        )
        TelemetryService.record_analytics_event(payload)

    @staticmethod
    def persist_and_broadcast_skip(
            candidate: Candidate,
            rank: int,
            reason: str,
    ) -> None:
        """
        Shortcut to persist a SKIP decision.
        """
        AnalyticsRecorder.persist_and_broadcast(
            candidate,
            rank=rank,
            decision="SKIP",
            reason=reason,
        )


class AiExecutionStage:
    """
    ChartAI gate + buy loop (persist decision before execution).
    Applies sizing and cash constraints, optionally attaches LI.FI route, then
    delegates execution to the Trader (PAPER vs LIVE handled downstream).
    """

    def __init__(self) -> None:
        self.trader = Trader()
        self.risk_manager = AdaptiveRiskManager()
        self.chart_ai = ChartAiSignalProvider()
        self.chart_ai_top_k: int = settings.TOP_K_CANDIDATES_FOR_CHART_AI
        self.chart_ai_timeframe_minutes: int = settings.CHART_AI_TIMEFRAME
        self.chart_ai_lookback_minutes: int = settings.CHART_AI_LOOKBACK_MINUTES
        self.minimum_entry_score: float = settings.SCORE_MIN_ENTRY

    @staticmethod
    def _current_free_cash_usd() -> float:
        """
        Return the currently available cash in USD from the latest portfolio snapshot.
        """
        with _session() as db:
            snapshot = get_portfolio_snapshot(db, create_if_missing=True)
            return float(snapshot.cash or 0.0) if snapshot else 0.0

    @staticmethod
    def _compute_per_order_budget_usd(free_cash_usd: float) -> float:
        """
        Compute the per-order budget from free cash and configured fraction.
        """
        fraction = float(settings.TREND_PER_BUY_FRACTION)
        return max(1.0, free_cash_usd * fraction)

    @staticmethod
    def _compute_from_amount_wei(order_notional_usd: float, candidate: Candidate) -> Optional[int]:
        """
        Compute the native input amount (in wei) for a USD notional, assuming:

          tokens = notional_usd / price_usd
          native = tokens * price_native
          wei    = native * 1e18

        Assumes 18 decimals for the EVM native asset (ETH, MATIC, BNB, AVAX C-chain, ...).
        """
        token_information = candidate.dexscreener_token_information
        try:
            price_usd = float(token_information.price_usd)
            price_native = float(token_information.price_native)
            if price_usd <= 0.0 or price_native <= 0.0:
                return None

            token_amount = order_notional_usd / price_usd
            native_amount = token_amount * price_native
            wei_amount = int(native_amount * (10 ** 18))
            return wei_amount if wei_amount > 0 else None
        except Exception:
            return None

    @staticmethod
    def _compute_from_amount_lamports(order_notional_usd: float, candidate: Candidate) -> Optional[int]:
        """
        Compute the native input amount (in lamports) for a USD notional on Solana, assuming:

          tokens    = notional_usd / price_usd
          native    = tokens * price_native
          lamports  = native * 1e9

        Assumes 9 decimals for SOL.
        """
        try:
            token_information = candidate.dexscreener_token_information
            price_usd = float(token_information.price_usd)
            price_native = float(token_information.price_native)
            if price_usd <= 0.0 or price_native <= 0.0:
                return None

            token_amount = order_notional_usd / price_usd
            native_amount = token_amount * price_native
            lamports = int(native_amount * (10 ** 9))
            return lamports if lamports > 0 else None
        except Exception:
            return None

    def _maybe_attach_lifi_route_for_live(
            self,
            candidate: Candidate,
            *,
            order_notional_usd: float,
    ) -> Optional[LifiRoute]:
        """
        Build a LI.FI route for a same-chain swap when LIVE mode is enabled.

        - EVM chains: native -> ERC-20 (amount in wei)
        - Solana: SOL -> SPL (amount in lamports)
        """
        if settings.PAPER_MODE:
            return None

        token_information = candidate.dexscreener_token_information
        chain_key = (token_information.chain_id or "").strip().lower()

        # --- Solana path ----------------------------------------------------
        if chain_key == "solana":
            token_mint = (token_information.base_token.address or "").strip()
            if not token_mint:
                log.debug("[TREND][LIVE][ROUTE] Missing SPL token mint for %s on Solana.",
                          token_information.base_token.symbol)
                return None

            from_amount_lamports = self._compute_from_amount_lamports(order_notional_usd, candidate)
            if from_amount_lamports is None:
                log.debug(
                    "[TREND][LIVE][ROUTE] Cannot compute fromAmount (need price_usd & price_native) for %s on Solana.",
                    token_information.base_token.symbol,
                )
                return None

            try:
                sol_signer = build_default_solana_signer()
                from_address = sol_signer.address
            except Exception as exc:
                log.warning("[TREND][LIVE][ROUTE] Solana signer unavailable (%s).", exc)
                return None

            try:
                route = build_native_to_token_route(
                    chain_key="solana",
                    from_address=from_address,
                    to_token_address=token_mint,
                    from_amount_wei=from_amount_lamports,  # lamports here by design
                    slippage=0.03,
                )
                return route
            except Exception as exc:
                log.warning(
                    "[TREND][LIVE][ROUTE] LI.FI route build failed for %s on solana: %s",
                    token_information.base_token.symbol,
                    exc,
                )
                return None

        # --- EVM path -------------------------------------------------------
        chain_id = resolve_lifi_chain_id(chain_key)
        if chain_id is None:
            log.debug("[TREND][LIVE][ROUTE] Unsupported Dexscreener chain '%s'.", chain_key or "?")
            return None

        to_token_address = (token_information.base_token.address or "").strip()
        if not to_token_address:
            log.debug("[TREND][LIVE][ROUTE] Missing ERC-20 token address for %s.", token_information.base_token.symbol)
            return None

        from_amount_wei = self._compute_from_amount_wei(order_notional_usd, candidate)
        if from_amount_wei is None:
            log.debug(
                "[TREND][LIVE][ROUTE] Cannot compute fromAmount (need price_usd & price_native) for %s.",
                token_information.base_token.symbol,
            )
            return None

        try:
            evm_signer = build_default_evm_signer()
            evm_address = evm_signer.address
        except Exception as exc:
            log.warning("[TREND][LIVE][ROUTE] EVM signer unavailable (%s).", exc)
            return None

        try:
            route = build_native_to_token_route(
                chain_key=chain_key,
                from_address=evm_address,
                to_token_address=to_token_address,
                from_amount_wei=from_amount_wei,
                slippage=0.03,
            )
            return route
        except Exception as exc:
            log.warning(
                "[TREND][LIVE][ROUTE] LI.FI route build failed for %s on %s: %s",
                token_information.base_token.symbol,
                chain_key,
                exc,
            )
            return None

    def ai_gate_and_execute(self, candidates: List[Candidate], engine: ScoringEngine) -> None:
        """
        Run AI gating and execute eligible buys in a single pass.
        Persist every decision via telemetry before handing execution to the Trader.
        """
        free_cash = self._current_free_cash_usd()
        per_order_budget_usd = self._compute_per_order_budget_usd(free_cash)
        minimum_free_cash_usd = float(settings.TREND_MIN_FREE_CASH_USD)
        maximum_buys_per_run = int(settings.TREND_MAX_BUYS_PER_RUN)

        simulated_cash = free_cash
        executed_buys = 0
        ai_budget_remaining = max(0, self.chart_ai_top_k)

        for rank, candidate in enumerate(sorted(candidates, key=lambda x: x.statistics_score, reverse=True), start=1):
            if executed_buys >= maximum_buys_per_run:
                log.debug("[TREND][BUY] Max buys per run reached (%d).", maximum_buys_per_run)
                break

            entry_score = float(candidate.statistics_score)
            ai_probability = 0.0
            ai_delta = 0.0

            if ai_budget_remaining > 0:
                try:
                    signal = self.chart_ai.predict(
                        symbol=candidate.token.symbol,
                        chain_name=candidate.token.chain or None,
                        pair_address=candidate.token.pairAddress or None,
                        timeframe_minutes=self.chart_ai_timeframe_minutes,
                        lookback_minutes=self.chart_ai_lookback_minutes,
                        token_age_hours=float(candidate.dexscreener_token_information.age_hours),
                    )
                except Exception:
                    log.exception("[TREND][AI] ChartAI failed for %s", candidate.token.symbol)
                    signal = None
                ai_budget_remaining -= 1

                if signal is not None:
                    ai_delta = float(signal.quality_score_delta)
                    ai_probability = float(signal.probability_tp1_before_sl)
                    entry_score = engine.apply_ai_adjustment(float(candidate.statistics_score), ai_delta)

            candidate.ai_quality_delta = ai_delta
            candidate.ai_buy_probability = ai_probability
            candidate.entry_score = entry_score

            if entry_score < self.minimum_entry_score:
                AnalyticsRecorder.persist_and_broadcast(
                    candidate,
                    rank=rank,
                    decision="SKIP",
                    reason="ENTRY_SCORE_BELOW_MIN",
                )
                log.debug(
                    "[TREND][AI][DROP] %s — entry=%.2f < %.2f (stat=%.2f aiΔ=%.2f prob=%.3f)",
                    candidate.token.symbol,
                    entry_score,
                    self.minimum_entry_score,
                    candidate.statistics_score,
                    ai_delta,
                    ai_probability,
                )
                continue

            size_multiplier = self.risk_manager.size_multiplier(candidate)
            order_notional = max(0.0, per_order_budget_usd * size_multiplier)

            if simulated_cash < order_notional or (simulated_cash - order_notional) < minimum_free_cash_usd:
                AnalyticsRecorder.persist_and_broadcast(
                    candidate,
                    rank=rank,
                    decision="SKIP",
                    reason="INSUFFICIENT_CASH",
                    sizing_multiplier=size_multiplier,
                    order_notional_usd=order_notional,
                    free_cash_before_usd=simulated_cash,
                    free_cash_after_usd=simulated_cash,
                )
                log.debug(
                    "[TREND][BUY][CASH_SKIP] %s need=%.2f have=%.2f min_free=%.2f",
                    candidate.token.symbol,
                    order_notional,
                    simulated_cash,
                    minimum_free_cash_usd,
                )
                continue

            AnalyticsRecorder.persist_and_broadcast(
                candidate,
                rank=rank,
                decision="BUY",
                reason="OK",
                sizing_multiplier=size_multiplier,
                order_notional_usd=order_notional,
                free_cash_before_usd=simulated_cash,
                free_cash_after_usd=simulated_cash - order_notional,
            )

            lifi_route = self._maybe_attach_lifi_route_for_live(candidate, order_notional_usd=order_notional)
            if lifi_route is not None:
                log.info("[TREND][LIVE][ROUTE] Attached LI.FI route for %s on %s", candidate.token.symbol,
                         candidate.token.chain)
            else:
                if not settings.PAPER_MODE:
                    log.info(
                        "[TREND][LIVE][ROUTE] Could not attach LI.FI route for %s on %s; Trader may skip LIVE buy.",
                        candidate.token.symbol,
                        candidate.token.chain,
                    )

            token = Token(
                symbol=candidate.token.symbol,
                chain=candidate.token.chain,
                tokenAddress=candidate.token.tokenAddress,
                pairAddress=candidate.token.pairAddress
            )
            order_payload = OrderPayload(
                token=token,
                price=candidate.dexscreener_token_information.price_usd,
                order_notional=order_notional,
                original_candidate=candidate,
                lifi_route=lifi_route,
            )

            self.trader.buy(order_payload)

            executed_buys += 1
            simulated_cash -= order_notional

            log.info(
                "[TREND][BUY] %s quality=%.1f stat=%.1f entry=%.1f aiΔ=%.2f prob=%.3f size×=%.2f notional=%.2f",
                candidate.token.symbol,
                candidate.quality_score,
                candidate.statistics_score,
                entry_score,
                ai_delta,
                ai_probability,
                size_multiplier,
                order_notional,
            )

        log.info(
            "[TREND][SUMMARY] executed=%d / %d candidates (cash=%.2f → %.2f)",
            executed_buys,
            len(candidates),
            free_cash,
            simulated_cash,
        )

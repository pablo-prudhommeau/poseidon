from __future__ import annotations

from src.api.websocket.telemetry import TelemetryService
from src.configuration.config import _to_dict, settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.models import TradingEvaluation

logger = get_application_logger(__name__)


class TradingEvaluationRecorder:
    @staticmethod
    def persist_and_broadcast(
            candidate: TradingCandidate,
            rank: int,
            decision: str,
            reason: str,
            sizing_multiplier: float = 0.0,
            order_notional_usd: float = 0.0,
            free_cash_before_usd: float = 0.0,
            free_cash_after_usd: float = 0.0,
    ) -> None:
        final_score = candidate.entry_score if candidate.final_computed_score <= 0 else candidate.final_computed_score

        token_information = candidate.dexscreener_token_information
        base_token = token_information.base_token

        volume = token_information.volume
        liquidity = token_information.liquidity
        price_change = token_information.price_change
        transactions = token_information.transactions

        computed_buy_to_sell_ratio = 0.5
        if transactions and (transactions.h1 or transactions.h24):
            reference_bucket = transactions.h1 if transactions.h1 else transactions.h24
            total_transaction_count = reference_bucket.buys + reference_bucket.sells
            if total_transaction_count > 0:
                computed_buy_to_sell_ratio = reference_bucket.buys / total_transaction_count

        payload = TradingEvaluation(
            token_symbol=base_token.symbol.upper(),
            blockchain_network=str(token_information.chain_id),
            token_address=str(base_token.address),
            pair_address=str(token_information.pair_address),
            price_usd=token_information.price_usd or 0.0,
            price_native=token_information.price_native or 0.0,
            candidate_rank=rank,
            quality_score=candidate.quality_score,
            statistics_score=candidate.statistics_score,
            entry_score=candidate.entry_score,
            final_score=final_score,
            ai_probability_take_profit_before_stop_loss=candidate.ai_buy_probability,
            ai_quality_score_delta=candidate.ai_quality_delta,
            token_age_hours=token_information.age_hours,
            volume_m5_usd=volume.m5 if volume and volume.m5 is not None else 0.0,
            volume_h1_usd=volume.h1 if volume and volume.h1 is not None else 0.0,
            volume_h6_usd=volume.h6 if volume and volume.h6 is not None else 0.0,
            volume_h24_usd=volume.h24 if volume and volume.h24 is not None else 0.0,
            liquidity_usd=liquidity.usd if liquidity and liquidity.usd is not None else 0.0,
            price_change_percentage_m5=price_change.m5 if price_change and price_change.m5 is not None else 0.0,
            price_change_percentage_h1=price_change.h1 if price_change and price_change.h1 is not None else 0.0,
            price_change_percentage_h6=price_change.h6 if price_change and price_change.h6 is not None else 0.0,
            price_change_percentage_h24=price_change.h24 if price_change and price_change.h24 is not None else 0.0,
            transaction_count_m5=transactions.m5.total_transactions if transactions and transactions.m5 else 0,
            transaction_count_h1=transactions.h1.total_transactions if transactions and transactions.h1 else 0,
            transaction_count_h6=transactions.h6.total_transactions if transactions and transactions.h6 else 0,
            transaction_count_h24=transactions.h24.total_transactions if transactions and transactions.h24 else 0,
            buy_to_sell_ratio=computed_buy_to_sell_ratio,
            market_cap_usd=token_information.market_cap or 0.0,
            fully_diluted_valuation_usd=token_information.fully_diluted_valuation or 0.0,
            evaluated_at=get_current_local_datetime(),
            execution_decision=decision.upper(),
            sizing_multiplier=sizing_multiplier or 0.0,
            order_notional_value_usd=order_notional_usd or 0.0,
            free_cash_before_execution_usd=free_cash_before_usd or 0.0,
            free_cash_after_execution_usd=free_cash_after_usd or 0.0,
            raw_dexscreener_payload=token_information.model_dump(mode="json"),
            raw_configuration_settings=_to_dict(settings),
        )

        logger.info("[TRADING][EVALUATION] Token %s sequence evaluated -> Decision: %s | Reason: %s", payload.token_symbol, decision.upper(), reason)

        if decision.upper() == "BUY":
            TelemetryService.record_analytics_event(payload)

    def persist_and_broadcast_skip(evaluation_candidate: TradingCandidate, sequence_rank: int, exclusion_reason: str) -> None:
        TradingEvaluationRecorder.persist_and_broadcast(evaluation_candidate, rank=sequence_rank, decision="SKIP", reason=exclusion_reason)

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

import httpx

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAlertSeverity,
    AaveSentinelPositionSnapshot,
    AaveSentinelRiskStatus,
    AaveSentinelState,
    AaveSentinelStrategyDirection,
)
from src.core.structures.structures import DcaOrderStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.format_utils import format_currency, format_percent
from src.integrations.telegram.telegram_client import (
    edit_message_text,
    get_updates,
    register_bot_commands,
    send_alert as send_telegram_alert,
)
from src.integrations.telegram.telegram_structures import TelegramCallbackQuery, TelegramMessage
from src.logging.logger import get_application_logger
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.db import get_database_session

logger = get_application_logger(__name__)

SnapshotFetcher = Callable[[], Awaitable[Optional[AaveSentinelPositionSnapshot]]]


class AaveSentinelNotificationService:
    def __init__(self, fetch_position_snapshot: SnapshotFetcher) -> None:
        self._fetch_position_snapshot = fetch_position_snapshot
        self._http_client: Optional[httpx.AsyncClient] = None
        self._state = AaveSentinelState()
        self._last_telegram_update_id = 0
        self._initial_basis_usd: Optional[float] = settings.AAVE_INITIAL_DEPOSIT_USD

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def bootstrap_state_from_snapshot(self, position_snapshot: AaveSentinelPositionSnapshot) -> None:
        self._state.last_health_factor = position_snapshot.health_factor
        self._state.last_total_equity_usd = position_snapshot.total_strategy_equity_usd
        self._state.last_risk_status = self._resolve_risk_status(position_snapshot.health_factor)

    async def register_bot_commands(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.debug("[AAVE][SENTINEL][TELEGRAM] Bot command registration skipped because token is missing")
            return

        defined_commands = [{"command": "snapshot", "description": "Afficher le statut du portefeuille"}]
        try:
            is_registration_successful = await asyncio.to_thread(register_bot_commands, defined_commands)
            if is_registration_successful:
                logger.info("[AAVE][SENTINEL][TELEGRAM] Telegram bot commands registered")
                return

            logger.warning("[AAVE][SENTINEL][TELEGRAM] Telegram bot command registration was rejected")
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][TELEGRAM] Telegram bot command registration failed: %s", exception)

    async def process_telegram_commands(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            return

        try:
            telegram_updates = await asyncio.to_thread(get_updates, self._last_telegram_update_id + 1, ["message", "callback_query"], 0)
            for telegram_update in telegram_updates:
                self._last_telegram_update_id = telegram_update.update_id
                if telegram_update.message is not None:
                    await self._handle_message(telegram_update.message)
                    continue
                if telegram_update.callback_query is not None:
                    await self._handle_callback_query(telegram_update.callback_query)
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][TELEGRAM] Telegram update processing failed: %s", exception)

    async def send_alert(
            self,
            title: str,
            message: str,
            severity: AaveSentinelAlertSeverity = AaveSentinelAlertSeverity.INFO,
    ) -> None:
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.debug("[AAVE][SENTINEL][TELEGRAM] Alert skipped because Telegram credentials are missing")
            return

        severity_emoji_by_level = {
            AaveSentinelAlertSeverity.INFO: "ℹ️",
            AaveSentinelAlertSeverity.WARNING: "⚠️",
            AaveSentinelAlertSeverity.DANGER: "🚨",
            AaveSentinelAlertSeverity.SUCCESS: "✅",
            AaveSentinelAlertSeverity.CRITICAL: "💀",
        }
        current_timestamp = get_current_local_datetime().strftime("%H:%M:%S")
        formatted_title = f"{title} ({current_timestamp})"
        resolved_emoji_indicator = severity_emoji_by_level.get(severity, "ℹ️")

        try:
            await asyncio.to_thread(
                send_telegram_alert,
                formatted_title,
                message,
                resolved_emoji_indicator,
            )
            logger.info("[AAVE][SENTINEL][TELEGRAM] Alert dispatched: %s", title)
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][TELEGRAM] Alert dispatch failed: %s", exception)

    async def format_notification_message(self, position_snapshot: AaveSentinelPositionSnapshot) -> str:
        current_usd_to_eur_exchange_rate = await self._fetch_usd_eur_exchange_rate()

        def format_monetary_values(amount_in_usd: float) -> str:
            amount_in_eur = amount_in_usd * current_usd_to_eur_exchange_rate
            return f"{format_currency(amount_in_eur, 'EUR')} ({format_currency(amount_in_usd)})"

        performance_display_value = "N/A"
        if self._initial_basis_usd is not None:
            current_total_equity = position_snapshot.total_strategy_equity_usd
            absolute_profit_and_loss = current_total_equity - self._initial_basis_usd
            relative_profit_and_loss = 0.0
            if self._initial_basis_usd != 0:
                relative_profit_and_loss = absolute_profit_and_loss / abs(self._initial_basis_usd)

            performance_indicator = "🚀" if absolute_profit_and_loss >= 0 else "🔻"
            performance_display_value = (
                f"{performance_indicator} "
                f"{format_monetary_values(absolute_profit_and_loss)} "
                f"({format_percent(relative_profit_and_loss)})"
            )

        def format_asset_inventory_line(
                asset_symbol: str,
                asset_amount: float,
                asset_value_usd: float,
                asset_annual_percentage_yield: Optional[float] = None,
        ) -> str:
            inventory_line = f"  • {asset_symbol}: {asset_amount:.4f} ({format_monetary_values(asset_value_usd)})"
            if asset_annual_percentage_yield is not None:
                inventory_line = f"{inventory_line} @ {format_percent(asset_annual_percentage_yield)} APY"
            return inventory_line

        supply_inventory_lines = [
            format_asset_inventory_line(
                asset.symbol,
                asset.supply_amount,
                asset.supply_value_usd,
                asset.supply_annual_percentage_yield,
            )
            for asset in position_snapshot.assets
            if asset.supply_value_usd > 1.0
        ]
        debt_inventory_lines = [
            format_asset_inventory_line(
                asset.symbol,
                asset.debt_amount,
                asset.debt_value_usd,
                asset.borrow_annual_percentage_yield,
            )
            for asset in position_snapshot.assets
            if asset.debt_value_usd > 1.0
        ]
        wallet_inventory_lines = [
            format_asset_inventory_line(
                asset.symbol,
                asset.wallet_amount,
                asset.wallet_value_usd,
            )
            for asset in position_snapshot.assets
            if asset.wallet_value_usd > 1.0
        ]

        formatted_supply_section = "\n".join(supply_inventory_lines) or "  (Aucun)"
        formatted_debt_section = "\n".join(debt_inventory_lines) or "  (Aucune)"
        formatted_wallet_section = "\n".join(wallet_inventory_lines) or "  (Vide)"

        health_factor_indicator = self._resolve_health_factor_indicator(position_snapshot.health_factor)

        strategy_context_block = ""
        if (
                position_snapshot.strategy_direction != AaveSentinelStrategyDirection.NEUTRAL
                and position_snapshot.main_asset_symbol
                and position_snapshot.liquidation_price_usd is not None
        ):
            current_market_price_usd = position_snapshot.main_asset_price_usd or 0.0
            liquidation_price_usd = position_snapshot.liquidation_price_usd
            distance_to_liquidation = 0.0
            if current_market_price_usd > 0:
                distance_to_liquidation = abs(current_market_price_usd - liquidation_price_usd) / current_market_price_usd

            direction_indicator = "📉" if position_snapshot.strategy_direction == AaveSentinelStrategyDirection.LONG else "📈"
            strategy_context_block = (
                "\n<b>Stratégie</b>\n"
                "<b>----------</b>\n"
                f"🎯 Type : <b>{position_snapshot.strategy_direction.value}</b> sur {position_snapshot.main_asset_symbol}\n"
                f"💲 Prix actuel : <code>{format_currency(current_market_price_usd)}</code>\n"
                f"💀 Liquidation : <code>{format_currency(liquidation_price_usd)}</code>\n"
                f"📏 Distance : <b>{format_percent(distance_to_liquidation)}</b> {direction_indicator}\n"
            )

        initial_basis_display_value = self._initial_basis_usd or 0.0
        return (
            "<b>Statut du compte</b>\n"
            "<b>----------</b>\n"
            f"🏥 Santé : <code>{position_snapshot.health_factor:.2f}</code> {health_factor_indicator}\n"
            f"⚡ Levier : <code>x{position_snapshot.current_leverage:.2f}</code>\n"
            f"💎 Net Aave : <code>{format_monetary_values(position_snapshot.aave_net_worth_usd)}</code>\n"
            f"💰 Net Total : <code>{format_monetary_values(position_snapshot.total_strategy_equity_usd)}</code>\n"
            f"💵 PnL latent : {performance_display_value}\n"
            f"{strategy_context_block}\n"
            "<b>Positions Aave</b>\n"
            "<b>----------</b>\n"
            f"📈 Supply total : <code>{format_monetary_values(position_snapshot.total_collateral_usd)}</code>\n"
            f"{formatted_supply_section}\n\n"
            f"📉 Dette totale : <code>{format_monetary_values(position_snapshot.total_debt_usd)}</code>\n"
            f"{formatted_debt_section}\n\n"
            "<b>Wallet</b>\n"
            "<b>----------</b>\n"
            f"💼 Total : <code>{format_monetary_values(position_snapshot.total_wallet_usd)}</code>\n"
            f"{formatted_wallet_section}\n\n"
            "<b>Performance</b>\n"
            "<b>----------</b>\n"
            f"📊 Net APY : <code>{format_percent(position_snapshot.weighted_net_apy)}</code>\n"
            f"💰 Initial : <code>{format_monetary_values(initial_basis_display_value)}</code>"
        )

    async def evaluate_risk_and_notify(self, position_snapshot: AaveSentinelPositionSnapshot) -> None:
        evaluation_timestamp = get_current_local_datetime()
        current_risk_status = self._resolve_risk_status(position_snapshot.health_factor)
        current_total_equity_usd = position_snapshot.total_strategy_equity_usd

        is_notification_dispatch_required = False
        notification_severity = AaveSentinelAlertSeverity.INFO
        notification_title = ""

        if current_risk_status != self._state.last_risk_status:
            is_notification_dispatch_required = True
            if current_risk_status == AaveSentinelRiskStatus.OPTIMAL:
                notification_severity = AaveSentinelAlertSeverity.SUCCESS
                notification_title = "Target atteinte"
            elif current_risk_status == AaveSentinelRiskStatus.NEUTRAL:
                if self._state.last_risk_status == AaveSentinelRiskStatus.OPTIMAL:
                    notification_severity = AaveSentinelAlertSeverity.INFO
                    notification_title = "Sortie de zone verte"
                else:
                    notification_severity = AaveSentinelAlertSeverity.SUCCESS
                    notification_title = "Retour au calme"
            elif current_risk_status == AaveSentinelRiskStatus.WARNING:
                notification_severity = AaveSentinelAlertSeverity.WARNING
                notification_title = "Statut warning"
            elif current_risk_status == AaveSentinelRiskStatus.DANGER:
                notification_severity = AaveSentinelAlertSeverity.DANGER
                notification_title = "Statut danger"
            else:
                notification_severity = AaveSentinelAlertSeverity.CRITICAL
                notification_title = "Statut critical"

        if (
                not is_notification_dispatch_required
                and current_risk_status in {
            AaveSentinelRiskStatus.WARNING,
            AaveSentinelRiskStatus.DANGER,
            AaveSentinelRiskStatus.CRITICAL,
        }
                and self._state.last_health_factor is not None
        ):
            health_factor_drop = self._state.last_health_factor - position_snapshot.health_factor
            if health_factor_drop > settings.AAVE_SIGNIFICANT_DEVIATION_HF:
                is_notification_dispatch_required = True
                notification_severity = self._map_risk_status_to_alert_severity(current_risk_status)
                notification_title = f"Chute rapide du HF (-{health_factor_drop:.2f})"

        if not is_notification_dispatch_required and self._state.last_total_equity_usd is not None:
            equity_drawdown_usd = self._state.last_total_equity_usd - current_total_equity_usd
            equity_drawdown_percentage = (
                equity_drawdown_usd / self._state.last_total_equity_usd
                if self._state.last_total_equity_usd > 0
                else 0.0
            )
            if equity_drawdown_percentage > settings.AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT:
                is_notification_dispatch_required = True
                notification_severity = AaveSentinelAlertSeverity.WARNING
                notification_title = f"Chute brutale de la valeur (-{format_percent(equity_drawdown_percentage)})"

        if not is_notification_dispatch_required and self._state.last_notification_time is not None:
            seconds_since_last_notification = (
                    evaluation_timestamp - self._state.last_notification_time
            ).total_seconds()
            if (
                    seconds_since_last_notification > settings.AAVE_ALERT_COOLDOWN_SECONDS
                    and current_risk_status != AaveSentinelRiskStatus.OPTIMAL
            ):
                is_notification_dispatch_required = True
                notification_severity = self._map_risk_status_to_alert_severity(current_risk_status)
                notification_title = f"Rappel statut {current_risk_status.value}"

        if is_notification_dispatch_required:
            detailed_alert_message = await self.format_notification_message(position_snapshot)
            await self.send_alert(notification_title, detailed_alert_message, notification_severity)
            self._state.last_notification_time = evaluation_timestamp

        self._state.last_health_factor = position_snapshot.health_factor
        self._state.last_total_equity_usd = current_total_equity_usd
        self._state.last_risk_status = current_risk_status

    async def _fetch_usd_eur_exchange_rate(self) -> float:
        fallback_exchange_rate = 0.95
        fx_provider_api_url = "https://api.frankfurter.dev/v1/latest?from=USD&to=EUR"

        try:
            http_client = await self._get_http_client()
            response = await http_client.get(fx_provider_api_url)
            response.raise_for_status()
            return float(response.json()["rates"]["EUR"])
        except Exception as exception:
            logger.exception(
                "[AAVE][SENTINEL][FX] Exchange rate fetch failed, using fallback %0.2f: %s",
                fallback_exchange_rate,
                exception,
            )
            return fallback_exchange_rate

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def _handle_message(self, telegram_message: TelegramMessage) -> None:
        if telegram_message.text is None:
            return

        normalized_message_text = telegram_message.text.strip()
        if normalized_message_text != "/snapshot":
            return

        logger.info("[AAVE][SENTINEL][TELEGRAM] Manual snapshot requested")
        await self.send_alert("Snapshot demandé", "📸 Calcul du snapshot en cours...", AaveSentinelAlertSeverity.INFO)
        current_position_snapshot = await self._fetch_position_snapshot()
        if current_position_snapshot is None:
            await self.send_alert("Erreur", "Impossible de récupérer les données Aave.", AaveSentinelAlertSeverity.WARNING)
            return

        formatted_message = await self.format_notification_message(current_position_snapshot)
        await self.send_alert("Snapshot manuel", formatted_message, AaveSentinelAlertSeverity.INFO)

    async def _handle_callback_query(self, telegram_callback_query: TelegramCallbackQuery) -> None:
        if telegram_callback_query.message is None:
            logger.warning("[AAVE][SENTINEL][CALLBACK] Malformed callback query received")
            return

        interaction_callback_data = telegram_callback_query.data
        if not interaction_callback_data.startswith("approve_dca:") and not interaction_callback_data.startswith("reject_dca:"):
            return

        origin_message_identifier = telegram_callback_query.message.message_id
        target_order_identifier = int(interaction_callback_data.split(":")[1])
        is_approval_action = interaction_callback_data.startswith("approve_dca:")
        resolved_order_status = DcaOrderStatus.APPROVED if is_approval_action else DcaOrderStatus.REJECTED
        resolved_status_label = "APPROUVÉ ✅" if is_approval_action else "REJETÉ ❌"

        logger.info(
            "[AAVE][SENTINEL][CALLBACK] Processing %s for order id %s",
            resolved_order_status.value,
            target_order_identifier,
        )

        with get_database_session() as database_session:
            order_dao = DcaOrderDao(database_session)
            strategy_dao = DcaStrategyDao(database_session)
            target_dca_order = order_dao.retrieve_by_id(target_order_identifier)

            if target_dca_order is None:
                logger.error("[AAVE][SENTINEL][CALLBACK] DCA order id %s was not found", target_order_identifier)
                return

            target_dca_order.order_status = resolved_order_status.value
            order_dao.save(target_dca_order)
            database_session.commit()

            from src.core.dca.dca_manager import DcaManager

            dca_manager = DcaManager(database_session)
            strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)

            if strategy_instance is not None:
                base_message_details = dca_manager._generate_approval_message_body(target_dca_order, strategy_instance)
                full_confirmation_message = f"{base_message_details}✨ <b>Statut:</b> {resolved_status_label}"
                edit_message_text(
                    message_id=origin_message_identifier,
                    text=full_confirmation_message,
                )
            else:
                edit_message_text(
                    message_id=origin_message_identifier,
                    text=f"✅ Ordre #{target_order_identifier} {resolved_status_label} avec succès.",
                )

            cache_invalidator.mark_dirty(CacheRealm.DCA_STRATEGIES)
            logger.info(
                "[AAVE][SENTINEL][CALLBACK] DCA order id %s updated to %s",
                target_order_identifier,
                resolved_order_status.value,
            )

    def _resolve_risk_status(self, current_health_factor: float) -> AaveSentinelRiskStatus:
        if current_health_factor < settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
            return AaveSentinelRiskStatus.CRITICAL
        if current_health_factor < settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
            return AaveSentinelRiskStatus.DANGER
        if current_health_factor < settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            return AaveSentinelRiskStatus.WARNING
        if current_health_factor < settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
            return AaveSentinelRiskStatus.NEUTRAL
        return AaveSentinelRiskStatus.OPTIMAL

    def _resolve_health_factor_indicator(self, current_health_factor: float) -> str:
        if current_health_factor >= settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
            return "🟢"
        if current_health_factor >= settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            return "⚪"
        if current_health_factor >= settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
            return "🟡"
        if current_health_factor >= settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
            return "🟠"
        return "🔴"

    def _map_risk_status_to_alert_severity(
            self,
            risk_status: AaveSentinelRiskStatus,
    ) -> AaveSentinelAlertSeverity:
        if risk_status == AaveSentinelRiskStatus.WARNING:
            return AaveSentinelAlertSeverity.WARNING
        if risk_status == AaveSentinelRiskStatus.DANGER:
            return AaveSentinelAlertSeverity.DANGER
        if risk_status == AaveSentinelRiskStatus.CRITICAL:
            return AaveSentinelAlertSeverity.CRITICAL
        if risk_status == AaveSentinelRiskStatus.OPTIMAL:
            return AaveSentinelAlertSeverity.SUCCESS
        return AaveSentinelAlertSeverity.INFO

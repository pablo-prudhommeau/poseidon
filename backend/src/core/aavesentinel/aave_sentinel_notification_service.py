from __future__ import annotations

import asyncio
import html
from typing import Optional

import httpx

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAlertSeverity,
    AaveSentinelCapitalFlowSummary,
    AaveSentinelFrankfurterExchangeRateResponse,
    AaveSentinelNotificationState,
    AaveSentinelPositionSnapshot,
    AaveSentinelRiskStatus,
    AaveSentinelStrategyDirection,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_aave_net_worth_usd,
    compute_latent_profit_and_loss_usd,
    compute_position_current_leverage,
    compute_position_total_wallet_usd,
    compute_position_weighted_net_apy,
    compute_total_strategy_equity_usd,
)
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders import resolve_aave_sentinel_state_for_display
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.format_utils import format_currency, format_percent
from src.integrations.telegram.telegram_client import (
    edit_message_text,
    register_bot_commands,
    send_alert as send_telegram_alert,
)
from src.integrations.telegram.telegram_format_utils import (
    TELEGRAM_MAIN_TITLE_BODY_SEPARATOR,
    build_telegram_section_block,
)
from src.integrations.telegram.telegram_structures import TelegramMessage
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelNotificationService:
    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None
        self._state = AaveSentinelNotificationState()

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def bootstrap_state_from_snapshot(self, position_snapshot: AaveSentinelPositionSnapshot) -> None:
        total_strategy_equity_usd = compute_total_strategy_equity_usd(
            total_collateral_usd=position_snapshot.total_collateral_usd,
            total_debt_usd=position_snapshot.total_debt_usd,
            assets=position_snapshot.assets,
        )
        self._state.last_health_factor = position_snapshot.health_factor
        self._state.last_total_equity_usd = total_strategy_equity_usd
        self._state.last_risk_status = self._resolve_risk_status(position_snapshot.health_factor)

    async def register_bot_commands(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.debug("[AAVESENTINEL][TELEGRAM] Bot command registration skipped because token is missing")
            return

        defined_commands = [{"command": "snapshot", "description": "Afficher le statut du portefeuille"}]
        try:
            is_registration_successful = await asyncio.to_thread(register_bot_commands, defined_commands)
            if is_registration_successful:
                logger.debug("[AAVESENTINEL][TELEGRAM] Telegram bot commands registered")
                return

            logger.warning("[AAVESENTINEL][TELEGRAM] Telegram bot command registration was rejected")
        except Exception as exception:
            logger.exception("[AAVESENTINEL][TELEGRAM] Telegram bot command registration failed: %s", exception)

    async def send_alert(
            self,
            title: str,
            message: str,
            severity: AaveSentinelAlertSeverity = AaveSentinelAlertSeverity.INFO,
    ) -> Optional[int]:
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.debug("[AAVESENTINEL][TELEGRAM] Alert skipped because Telegram credentials are missing")
            return None

        resolved_emoji_indicator = self._resolve_alert_severity_emoji(alert_severity=severity)

        try:
            message_identifier = await asyncio.to_thread(
                send_telegram_alert,
                title=self._format_alert_title(title=title),
                body=message,
                emoji_indicator=resolved_emoji_indicator,
                reply_markup=None,
                title_body_separator=TELEGRAM_MAIN_TITLE_BODY_SEPARATOR,
            )
            logger.debug("[AAVESENTINEL][TELEGRAM] Alert dispatched: %s", title)
            return message_identifier
        except Exception as exception:
            logger.exception("[AAVESENTINEL][TELEGRAM] Alert dispatch failed: %s", exception)
            return None

    async def edit_alert(
            self,
            message_id: int,
            title: str,
            message: str,
            severity: AaveSentinelAlertSeverity = AaveSentinelAlertSeverity.INFO,
    ) -> bool:
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.debug("[AAVESENTINEL][TELEGRAM] Alert edit skipped because Telegram credentials are missing")
            return False

        resolved_emoji_indicator = self._resolve_alert_severity_emoji(alert_severity=severity)
        formatted_message_text = self._format_alert_message_text(
            title=title,
            message=message,
            emoji_indicator=resolved_emoji_indicator,
        )

        try:
            is_edit_successful = await asyncio.to_thread(
                edit_message_text,
                message_id=message_id,
                text=formatted_message_text,
            )
            if is_edit_successful:
                logger.debug("[AAVESENTINEL][TELEGRAM] Alert edited: %s message_id=%s", title, message_id)
            return is_edit_successful
        except Exception as exception:
            logger.exception("[AAVESENTINEL][TELEGRAM] Alert edit failed: %s", exception)
            return False

    def _format_alert_title(self, title: str) -> str:
        current_timestamp = get_current_local_datetime().strftime("%H:%M:%S")
        return f"{title} ({current_timestamp})"

    def _format_alert_message_text(
            self,
            title: str,
            message: str,
            emoji_indicator: str,
    ) -> str:
        formatted_title = self._format_alert_title(title=title)
        header_text: str = f"{emoji_indicator} {formatted_title}".strip()
        return f"<b>{html.escape(header_text)}</b>{TELEGRAM_MAIN_TITLE_BODY_SEPARATOR}{message}"

    async def format_notification_message(
            self,
            position_snapshot: AaveSentinelPositionSnapshot,
            capital_flow_summary: Optional[AaveSentinelCapitalFlowSummary] = None,
    ) -> str:
        if capital_flow_summary is None:
            sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()
            capital_flow_summary = sentinel_state.capital_flow_summary

        if capital_flow_summary is None:
            capital_flow_summary = AaveSentinelCapitalFlowSummary()

        current_usd_to_eur_exchange_rate = await self._fetch_usd_eur_exchange_rate()

        def format_monetary_values(amount_in_usd: float) -> str:
            amount_in_eur = amount_in_usd * current_usd_to_eur_exchange_rate
            return f"{format_currency(amount_in_eur, 'EUR')} ({format_currency(amount_in_usd)})"

        total_strategy_equity_usd = compute_total_strategy_equity_usd(
            total_collateral_usd=position_snapshot.total_collateral_usd,
            total_debt_usd=position_snapshot.total_debt_usd,
            assets=position_snapshot.assets,
        )
        aave_net_worth_usd = compute_aave_net_worth_usd(
            total_collateral_usd=position_snapshot.total_collateral_usd,
            total_debt_usd=position_snapshot.total_debt_usd,
        )
        total_wallet_usd = compute_position_total_wallet_usd(assets=position_snapshot.assets)
        current_leverage = compute_position_current_leverage(
            total_collateral_usd=position_snapshot.total_collateral_usd,
            total_debt_usd=position_snapshot.total_debt_usd,
        )
        weighted_net_apy = compute_position_weighted_net_apy(assets=position_snapshot.assets)

        performance_display_value = "N/A"
        absolute_profit_and_loss = compute_latent_profit_and_loss_usd(
            total_equity_usd=total_strategy_equity_usd,
            net_capital_deployed_usd=capital_flow_summary.net_capital_deployed_usd,
        )
        relative_profit_and_loss = 0.0
        net_capital_deployed_usd = capital_flow_summary.net_capital_deployed_usd
        if net_capital_deployed_usd != 0:
            relative_profit_and_loss = absolute_profit_and_loss / abs(net_capital_deployed_usd)

        performance_indicator = "🚀" if absolute_profit_and_loss >= 0 else "🔻"
        if net_capital_deployed_usd == 0:
            performance_display_value = (
                f"{performance_indicator} "
                f"{format_monetary_values(absolute_profit_and_loss)} "
                f"(N/A)"
            )
        else:
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
            if asset.supply_amount > 0
        ]
        debt_inventory_lines = [
            format_asset_inventory_line(
                asset.symbol,
                asset.debt_amount,
                asset.debt_value_usd,
                asset.borrow_annual_percentage_yield,
            )
            for asset in position_snapshot.assets
            if asset.debt_amount > 0
        ]
        wallet_inventory_lines = [
            format_asset_inventory_line(
                asset.symbol,
                asset.wallet_amount,
                asset.wallet_value_usd,
            )
            for asset in position_snapshot.assets
            if asset.wallet_amount > 0
        ]

        formatted_supply_section = "\n".join(supply_inventory_lines) or "  (Aucun)"
        formatted_debt_section = "\n".join(debt_inventory_lines) or "  (Aucune)"
        formatted_wallet_section = "\n".join(wallet_inventory_lines) or "  (Vide)"

        health_factor_indicator = self._resolve_health_factor_indicator(position_snapshot.health_factor)

        account_status_section_lines: list[str] = [
            f"🏥 Santé : <code>{position_snapshot.health_factor:.2f}</code> {health_factor_indicator}",
            f"⚡ Levier : <code>x{current_leverage:.2f}</code>",
            f"💎 Net Aave : <code>{format_monetary_values(aave_net_worth_usd)}</code>",
            f"💰 Net Total : <code>{format_monetary_values(total_strategy_equity_usd)}</code>",
            f"💵 PnL latent : {performance_display_value}",
        ]
        message_sections: list[str] = [
            build_telegram_section_block("Statut du compte", account_status_section_lines),
        ]

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
            strategy_section_lines: list[str] = [
                f"🎯 Type : <b>{position_snapshot.strategy_direction.value}</b> sur {position_snapshot.main_asset_symbol}",
                f"💲 Prix actuel : <code>{format_currency(current_market_price_usd)}</code>",
                f"💀 Liquidation : <code>{format_currency(liquidation_price_usd)}</code>",
                f"📏 Distance : <b>{format_percent(distance_to_liquidation)}</b> {direction_indicator}",
            ]
            message_sections.append(build_telegram_section_block("Stratégie", strategy_section_lines))

        aave_positions_section_lines: list[str] = [
            f"📈 Supply total : <code>{format_monetary_values(position_snapshot.total_collateral_usd)}</code>",
            formatted_supply_section,
            "",
            f"📉 Dette totale : <code>{format_monetary_values(position_snapshot.total_debt_usd)}</code>",
            formatted_debt_section,
        ]
        message_sections.append(build_telegram_section_block("Positions Aave", aave_positions_section_lines))

        wallet_section_lines: list[str] = [
            f"💼 Total : <code>{format_monetary_values(total_wallet_usd)}</code>",
            formatted_wallet_section,
        ]
        message_sections.append(build_telegram_section_block("Wallet", wallet_section_lines))

        performance_section_lines: list[str] = [
            f"📊 Net APY actuelle : <code>{format_percent(weighted_net_apy)}</code>",
            f"📥 Entrées : <code>{format_monetary_values(capital_flow_summary.total_inflow_usd)}</code>",
            f"📤 Sorties : <code>{format_monetary_values(capital_flow_summary.total_outflow_usd)}</code>",
            f"💼 Capital net : <code>{format_monetary_values(capital_flow_summary.net_capital_deployed_usd)}</code>",
        ]
        message_sections.append(build_telegram_section_block("Performance", performance_section_lines))

        return "\n".join(section for section in message_sections if section)

    async def evaluate_risk_and_notify(self, position_snapshot: AaveSentinelPositionSnapshot) -> None:
        evaluation_timestamp = get_current_local_datetime()
        current_risk_status = self._resolve_risk_status(position_snapshot.health_factor)
        current_total_equity_usd = compute_total_strategy_equity_usd(
            total_collateral_usd=position_snapshot.total_collateral_usd,
            total_debt_usd=position_snapshot.total_debt_usd,
            assets=position_snapshot.assets,
        )

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
            if health_factor_drop > settings.AAVE_SENTINEL_SIGNIFICANT_DEVIATION_HF:
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
            if equity_drawdown_percentage > settings.AAVE_SENTINEL_SIGNIFICANT_DEVIATION_EQUITY_PCT:
                is_notification_dispatch_required = True
                notification_severity = AaveSentinelAlertSeverity.WARNING
                notification_title = f"Chute brutale de la valeur (-{format_percent(equity_drawdown_percentage)})"

        if not is_notification_dispatch_required and self._state.last_notification_time is not None:
            seconds_since_last_notification = (
                    evaluation_timestamp - self._state.last_notification_time
            ).total_seconds()
            if (
                    seconds_since_last_notification > settings.AAVE_SENTINEL_ALERT_COOLDOWN_SECONDS
                    and current_risk_status != AaveSentinelRiskStatus.OPTIMAL
            ):
                is_notification_dispatch_required = True
                notification_severity = self._map_risk_status_to_alert_severity(current_risk_status)
                notification_title = f"Rappel statut {current_risk_status.value}"

        if is_notification_dispatch_required:
            detailed_alert_message = await self.format_notification_message(position_snapshot=position_snapshot)
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
            response_payload = AaveSentinelFrankfurterExchangeRateResponse.model_validate(response.json())
            if response_payload.rates.EUR is None:
                raise RuntimeError("Frankfurter response missing EUR rate")
            return response_payload.rates.EUR
        except Exception as exception:
            logger.exception(
                "[AAVESENTINEL][FX] Exchange rate fetch failed, using fallback %0.2f: %s",
                fallback_exchange_rate,
                exception,
            )
            return fallback_exchange_rate

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def handle_telegram_message(self, telegram_message: TelegramMessage) -> None:
        if telegram_message.text is None:
            return

        normalized_message_text = telegram_message.text.strip()
        if normalized_message_text != "/snapshot":
            return

        logger.debug("[AAVESENTINEL][TELEGRAM] Manual snapshot requested")
        progress_message_id = await self.send_alert(
            "Snapshot demandé",
            "📸 Calcul du snapshot en cours...",
            AaveSentinelAlertSeverity.INFO,
        )
        sentinel_state = await resolve_aave_sentinel_state_for_display()
        current_position_snapshot = sentinel_state.position_snapshot
        if current_position_snapshot is None:
            if progress_message_id is not None:
                await self.edit_alert(
                    message_id=progress_message_id,
                    title="Erreur",
                    message="Impossible de récupérer les données Aave.",
                    severity=AaveSentinelAlertSeverity.WARNING,
                )
            else:
                await self.send_alert(
                    "Erreur",
                    "Impossible de récupérer les données Aave.",
                    AaveSentinelAlertSeverity.WARNING,
                )
            return

        formatted_message = await self.format_notification_message(
            position_snapshot=current_position_snapshot,
            capital_flow_summary=sentinel_state.capital_flow_summary,
        )
        if progress_message_id is not None:
            await self.edit_alert(
                message_id=progress_message_id,
                title="Snapshot manuel",
                message=formatted_message,
                severity=AaveSentinelAlertSeverity.INFO,
            )
            return

        await self.send_alert(
            "Snapshot manuel",
            formatted_message,
            AaveSentinelAlertSeverity.INFO,
        )

    def _resolve_risk_status(self, current_health_factor: float) -> AaveSentinelRiskStatus:
        if current_health_factor < settings.AAVE_SENTINEL_HEALTH_FACTOR_DANGER_THRESHOLD:
            return AaveSentinelRiskStatus.CRITICAL
        if current_health_factor < settings.AAVE_SENTINEL_HEALTH_FACTOR_WARNING_THRESHOLD:
            return AaveSentinelRiskStatus.DANGER
        if current_health_factor < settings.AAVE_SENTINEL_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            return AaveSentinelRiskStatus.WARNING
        if current_health_factor < settings.AAVE_SENTINEL_HEALTH_FACTOR_RELOOP_THRESHOLD:
            return AaveSentinelRiskStatus.NEUTRAL
        return AaveSentinelRiskStatus.OPTIMAL

    def _resolve_health_factor_indicator(self, current_health_factor: float) -> str:
        if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_RELOOP_THRESHOLD:
            return "🟢"
        if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            return "⚪"
        if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_WARNING_THRESHOLD:
            return "🟡"
        if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_DANGER_THRESHOLD:
            return "🟠"
        return "🔴"

    def _resolve_alert_severity_emoji(self, alert_severity: AaveSentinelAlertSeverity) -> str:
        if alert_severity == AaveSentinelAlertSeverity.WARNING:
            return "⚠️"
        if alert_severity == AaveSentinelAlertSeverity.DANGER:
            return "🚨"
        if alert_severity == AaveSentinelAlertSeverity.SUCCESS:
            return "✅"
        if alert_severity == AaveSentinelAlertSeverity.CRITICAL:
            return "💀"
        return "ℹ️"

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

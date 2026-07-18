from __future__ import annotations

import asyncio
from typing import Callable, Optional

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAlertSeverity,
    AaveSentinelCapitalFlowSummary,
    AaveSentinelNotificationState,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelRiskStatus,
    AaveSentinelStrategyCycleSummary,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_total_strategy_equity_usd,
)
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders import resolve_aave_sentinel_state_for_display
from src.core.aavesentinel.notification.aave_sentinel_notification_constants import (
    AAVE_SENTINEL_PNL_NOTIFICATION_TITLE,
    AAVE_SENTINEL_SNAPSHOT_NOTIFICATION_TITLE,
    AAVE_SENTINEL_TELEGRAM_TITLE_BODY_SEPARATOR,
)
from src.core.aavesentinel.notification.aave_sentinel_notification_format_helpers import (
    _build_balance_sheet_section_lines as build_balance_sheet_section_lines,
    build_notification_message,
    resolve_health_factor_indicator,
)
from src.core.aavesentinel.notification.aave_sentinel_notification_pnl_timeline_helpers import (
    _build_strategy_cycle_entry_exit_price_line as build_strategy_cycle_entry_exit_price_line,
    build_pnl_detail_message_pages,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.format_utils import format_percent
from src.integrations.frankfurter.frankfurter_client import FrankfurterClient
from src.integrations.telegram.telegram_client import (
    register_bot_commands,
    send_alert as send_telegram_alert,
    send_html_message as send_telegram_html_message,
)
from src.integrations.telegram.telegram_structures import TelegramMessage
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelNotificationService:

    def __init__(self) -> None:
        self._frankfurter_client = FrankfurterClient()
        self._state = AaveSentinelNotificationState()

    async def close(self) -> None:
        await self._frankfurter_client.close()

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

        defined_commands = [
            {"command": "snapshot", "description": AAVE_SENTINEL_SNAPSHOT_NOTIFICATION_TITLE},
            {"command": "pnl", "description": AAVE_SENTINEL_PNL_NOTIFICATION_TITLE},
        ]
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
                title_body_separator=AAVE_SENTINEL_TELEGRAM_TITLE_BODY_SEPARATOR,
            )
            logger.debug("[AAVESENTINEL][TELEGRAM] Alert dispatched: %s", title)
            return message_identifier
        except Exception as exception:
            logger.exception("[AAVESENTINEL][TELEGRAM] Alert dispatch failed: %s", exception)
            return None

    async def send_html_message(self, message: str) -> Optional[int]:
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.debug("[AAVESENTINEL][TELEGRAM] Html message skipped because Telegram credentials are missing")
            return None

        try:
            message_identifier = await asyncio.to_thread(
                send_telegram_html_message,
                text=message,
                reply_markup=None,
            )
            logger.debug("[AAVESENTINEL][TELEGRAM] Html message dispatched message_id=%s", message_identifier)
            return message_identifier
        except Exception as exception:
            logger.exception("[AAVESENTINEL][TELEGRAM] Html message dispatch failed: %s", exception)
            return None

    def _format_alert_title(self, title: str) -> str:
        current_timestamp = get_current_local_datetime().strftime("%H:%M:%S")
        return f"{title} ({current_timestamp})"

    async def format_notification_message(
            self,
            position_snapshot: AaveSentinelPositionSnapshot,
            capital_flow_summary: Optional[AaveSentinelCapitalFlowSummary] = None,
            performance_summary: Optional[AaveSentinelPerformanceSummary] = None,
    ) -> str:
        if capital_flow_summary is None or performance_summary is None:
            sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()
            if capital_flow_summary is None:
                capital_flow_summary = sentinel_state.capital_flow_summary
            if performance_summary is None:
                performance_summary = sentinel_state.performance_summary

        if capital_flow_summary is None:
            capital_flow_summary = AaveSentinelCapitalFlowSummary()
        if performance_summary is None:
            performance_summary = AaveSentinelPerformanceSummary()

        usd_eur_exchange_rate = await self._fetch_usd_eur_exchange_rate()
        return build_notification_message(
            position_snapshot=position_snapshot,
            usd_eur_exchange_rate=usd_eur_exchange_rate,
            capital_flow_summary=capital_flow_summary,
            performance_summary=performance_summary,
        )

    async def format_pnl_detail_message(
            self,
            performance_summary: AaveSentinelPerformanceSummary,
            position_snapshot: Optional[AaveSentinelPositionSnapshot] = None,
    ) -> str:
        pnl_detail_pages = await self.format_pnl_detail_message_pages(
            performance_summary=performance_summary,
            position_snapshot=position_snapshot,
        )
        if not pnl_detail_pages:
            return ""
        return pnl_detail_pages[0]

    async def format_pnl_detail_message_pages(
            self,
            performance_summary: AaveSentinelPerformanceSummary,
            position_snapshot: Optional[AaveSentinelPositionSnapshot] = None,
    ) -> list[str]:
        usd_eur_exchange_rate = await self._fetch_usd_eur_exchange_rate()
        return build_pnl_detail_message_pages(
            performance_summary=performance_summary,
            usd_eur_exchange_rate=usd_eur_exchange_rate,
            position_snapshot=position_snapshot,
        )

    async def send_pnl_detail_pages(self, formatted_pages: list[str]) -> None:
        if not formatted_pages:
            return
        total_page_count: int = len(formatted_pages)
        first_page_title: str = (
            AAVE_SENTINEL_PNL_NOTIFICATION_TITLE
            if total_page_count == 1
            else f"{AAVE_SENTINEL_PNL_NOTIFICATION_TITLE} (1/{total_page_count})"
        )
        await self.send_alert(
            first_page_title,
            formatted_pages[0],
            AaveSentinelAlertSeverity.INFO,
        )
        for page_index in range(1, total_page_count):
            await self.send_html_message(message=formatted_pages[page_index])

    def _build_balance_sheet_section_lines(
            self,
            performance_summary: AaveSentinelPerformanceSummary,
            capital_flow_summary: AaveSentinelCapitalFlowSummary,
            format_monetary_values: Callable[[float], str],
    ) -> list[str]:
        return build_balance_sheet_section_lines(
            performance_summary=performance_summary,
            capital_flow_summary=capital_flow_summary,
            format_monetary_values=format_monetary_values,
        )

    def _build_strategy_cycle_entry_exit_price_line(
            self,
            strategy_cycle: AaveSentinelStrategyCycleSummary,
            position_snapshot: Optional[AaveSentinelPositionSnapshot] = None,
    ) -> Optional[str]:
        return build_strategy_cycle_entry_exit_price_line(
            strategy_cycle=strategy_cycle,
            position_snapshot=position_snapshot,
        )

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
        try:
            return await self._frankfurter_client.fetch_usd_to_euro_latest_rate()
        except Exception as exception:
            logger.exception(
                "[AAVESENTINEL][FX] Exchange rate fetch failed, using fallback %0.2f: %s",
                fallback_exchange_rate,
                exception,
            )
            return fallback_exchange_rate

    async def handle_telegram_message(self, telegram_message: TelegramMessage) -> None:
        if telegram_message.text is None:
            return

        normalized_message_text = telegram_message.text.strip()
        if normalized_message_text == "/snapshot":
            await self._handle_snapshot_command()
            return
        if normalized_message_text == "/pnl":
            await self._handle_pnl_command()
            return

    async def _handle_snapshot_command(self) -> None:
        logger.debug("[AAVESENTINEL][TELEGRAM] Manual snapshot requested")
        sentinel_state = await resolve_aave_sentinel_state_for_display()
        current_position_snapshot = sentinel_state.position_snapshot
        if current_position_snapshot is None:
            await self.send_alert(
                "Erreur",
                "Impossible de récupérer les données Aave.",
                AaveSentinelAlertSeverity.WARNING,
            )
            return

        formatted_message = await self.format_notification_message(
            position_snapshot=current_position_snapshot,
            capital_flow_summary=sentinel_state.capital_flow_summary,
            performance_summary=sentinel_state.performance_summary,
        )
        await self.send_alert(
            AAVE_SENTINEL_SNAPSHOT_NOTIFICATION_TITLE,
            formatted_message,
            AaveSentinelAlertSeverity.INFO,
        )

    async def _handle_pnl_command(self) -> None:
        logger.debug("[AAVESENTINEL][TELEGRAM] Manual PnL detail requested")
        sentinel_state = await resolve_aave_sentinel_state_for_display()
        performance_summary = sentinel_state.performance_summary
        if performance_summary is None or not performance_summary.is_available:
            await self.send_alert(
                "Erreur",
                "Impossible de calculer le bilan trading et APY.",
                AaveSentinelAlertSeverity.WARNING,
            )
            return

        formatted_pages = await self.format_pnl_detail_message_pages(
            performance_summary=performance_summary,
            position_snapshot=sentinel_state.position_snapshot,
        )
        if not formatted_pages:
            await self.send_alert(
                "Erreur",
                "Impossible de formater le bilan trading et APY.",
                AaveSentinelAlertSeverity.WARNING,
            )
            return
        await self.send_pnl_detail_pages(formatted_pages=formatted_pages)

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
        return resolve_health_factor_indicator(current_health_factor=current_health_factor)

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

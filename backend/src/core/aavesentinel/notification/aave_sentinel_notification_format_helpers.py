from __future__ import annotations

from typing import Callable, Optional

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelStrategy,
    AaveSentinelStrategyKind,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_aave_net_worth_usd,
    compute_position_total_wallet_usd,
    compute_position_weighted_net_apy,
    compute_total_strategy_equity_usd,
)
from src.core.aavesentinel.notification.aave_sentinel_notification_structures import (
    AaveSentinelNotificationInventoryEntry,
    AaveSentinelNotificationInventoryRow,
)
from src.core.utils.format_utils import format_currency, format_percent
from src.core.utils.symbol_utils import get_currency_symbol
from src.integrations.telegram.telegram_format_utils import build_telegram_section_block

_TELEGRAM_DUAL_CURRENCY_SEPARATOR: str = " · "
_TELEGRAM_INVENTORY_TOKEN_VALUE_GAP: str = "\u00a0\u00a0\u00a0"


def _telegram_monospace_display_width(text: str) -> int:
    return len(text)


def _pad_telegram_monospace_end(text: str, width: int) -> str:
    padding_count: int = max(0, width - _telegram_monospace_display_width(text))
    return text + ("\u00a0" * padding_count)


def _format_compact_token_amount_label(asset_amount: float) -> str:
    if abs(asset_amount) >= 1.0:
        return f"{asset_amount:.2f}"
    return f"{asset_amount:.4f}"


def _format_token_quantity_value_label(asset_symbol: str, asset_amount: float) -> str:
    currency_glyph: str = get_currency_symbol(asset_symbol)
    amount_column_label: str = _format_compact_token_amount_label(asset_amount)
    if currency_glyph and currency_glyph != asset_symbol:
        return f"{amount_column_label}{currency_glyph}"
    return amount_column_label


def _format_dual_currency_values(amount_usd: float, usd_eur_exchange_rate: float) -> str:
    amount_eur: float = amount_usd * usd_eur_exchange_rate
    return (
        f"{format_currency(amount_eur, currency='EUR')}"
        f"{_TELEGRAM_DUAL_CURRENCY_SEPARATOR}"
        f"{format_currency(amount_usd)}"
    )


def _build_inventory_asset_rows(
        inventory_entries: list[AaveSentinelNotificationInventoryEntry],
) -> list[AaveSentinelNotificationInventoryRow]:
    inventory_asset_rows: list[AaveSentinelNotificationInventoryRow] = []
    for inventory_entry in inventory_entries:
        inventory_value_parts: list[str] = [
            _format_token_quantity_value_label(
                asset_symbol=inventory_entry.asset_symbol,
                asset_amount=inventory_entry.asset_amount,
            ),
            format_currency(inventory_entry.asset_value_usd),
        ]
        if inventory_entry.asset_annual_percentage_yield is not None:
            inventory_value_parts.append(
                f"{format_percent(inventory_entry.asset_annual_percentage_yield)} APY"
            )
        inventory_asset_rows.append(
            AaveSentinelNotificationInventoryRow(
                token_symbol=inventory_entry.asset_symbol,
                values_label=_TELEGRAM_DUAL_CURRENCY_SEPARATOR.join(inventory_value_parts),
            )
        )
    return inventory_asset_rows


def _format_inventory_monospace_line(
        inventory_asset_row: AaveSentinelNotificationInventoryRow,
        token_column_width: int,
) -> str:
    padded_token_symbol: str = _pad_telegram_monospace_end(
        inventory_asset_row.token_symbol,
        token_column_width,
    )
    return (
        f"{padded_token_symbol}"
        f"{_TELEGRAM_INVENTORY_TOKEN_VALUE_GAP}"
        f"{inventory_asset_row.values_label}"
    )


def _format_inventory_section_lines(
        inventory_asset_rows: list[AaveSentinelNotificationInventoryRow],
        token_column_width: int,
        section_emoji: Optional[str] = None,
        section_label: Optional[str] = None,
        section_total_label: Optional[str] = None,
) -> list[str]:
    asset_monospace_lines: list[str] = [
        _format_inventory_monospace_line(
            inventory_asset_row=inventory_asset_row,
            token_column_width=token_column_width,
        )
        for inventory_asset_row in inventory_asset_rows
    ]
    section_lines: list[str] = []
    if section_emoji is not None and section_label is not None:
        if section_total_label is not None:
            section_lines.append(f"{section_emoji} {section_label} ({section_total_label})")
        else:
            section_lines.append(f"{section_emoji} {section_label}")
    if len(asset_monospace_lines) > 0:
        section_lines.append(f"<code>{chr(10).join(asset_monospace_lines)}</code>")
    return section_lines


def _format_latent_pnl_display(
        amount_usd: float,
        net_capital_deployed_usd: float,
        format_monetary_values: Callable[[float], str],
) -> str:
    latent_pnl_indicator: str = "🚀" if amount_usd >= 0 else "🔻"
    if net_capital_deployed_usd == 0:
        monetary_values_label: str = f"{format_monetary_values(amount_usd)} (N/A)"
        return f"{latent_pnl_indicator} <code>{monetary_values_label}</code>"
    relative_profit_and_loss: float = amount_usd / abs(net_capital_deployed_usd)
    monetary_values_label = (
        f"{format_monetary_values(amount_usd)} "
        f"({format_percent(relative_profit_and_loss)})"
    )
    return f"{latent_pnl_indicator} <code>{monetary_values_label}</code>"


def _build_balance_sheet_section_lines(
        performance_summary: AaveSentinelPerformanceSummary,
        capital_flow_summary: AaveSentinelCapitalFlowSummary,
        format_monetary_values: Callable[[float], str],
) -> list[str]:
    latent_pnl_display: str = _format_latent_pnl_display(
        amount_usd=performance_summary.global_pnl_usd,
        net_capital_deployed_usd=capital_flow_summary.net_capital_deployed_usd,
        format_monetary_values=format_monetary_values,
    )
    return [
        f"💵 PnL : {latent_pnl_display}",
        f"🏦 Dont APY : <code>{format_monetary_values(performance_summary.cumulative_net_interest_usd)}</code>",
    ]


def _build_strategies_section_lines(strategies: list[AaveSentinelStrategy]) -> list[str]:
    strategy_section_lines: list[str] = []
    for strategy_index, strategy in enumerate(strategies):
        if strategy_index > 0:
            strategy_section_lines.append("")
        strategy_kind_emoji: str = (
            "📈"
            if strategy.kind == AaveSentinelStrategyKind.LONG
            else "📉"
        )
        strategy_section_lines.append(
            f"{strategy_kind_emoji} <b>{strategy.kind.value}</b> {strategy.main_asset_symbol}"
            f"  ⚡ ×{strategy.leverage:.2f}"
        )
        strategy_detail_parts: list[str] = [
            f"🏷️ {format_currency(strategy.main_asset_price_usd)}",
        ]
        if strategy.debt_usd > 0 and strategy.liquidation_price_usd > 0:
            distance_to_liquidation: float = 0.0
            if strategy.main_asset_price_usd > 0:
                distance_to_liquidation = (
                        abs(strategy.main_asset_price_usd - strategy.liquidation_price_usd)
                        / strategy.main_asset_price_usd
                )
            strategy_detail_parts.append(f"💀 {format_currency(strategy.liquidation_price_usd)}")
            strategy_detail_parts.append(f"📏 {format_percent(distance_to_liquidation)}")
        strategy_section_lines.append(
            f"   {_TELEGRAM_DUAL_CURRENCY_SEPARATOR.join(strategy_detail_parts)}"
        )
    return strategy_section_lines


def resolve_health_factor_indicator(current_health_factor: float) -> str:
    if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_RELOOP_THRESHOLD:
        return "🟢"
    if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
        return "⚪"
    if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_WARNING_THRESHOLD:
        return "🟡"
    if current_health_factor >= settings.AAVE_SENTINEL_HEALTH_FACTOR_DANGER_THRESHOLD:
        return "🟠"
    return "🔴"


def build_notification_message(
        position_snapshot: AaveSentinelPositionSnapshot,
        usd_eur_exchange_rate: float,
        capital_flow_summary: AaveSentinelCapitalFlowSummary,
        performance_summary: AaveSentinelPerformanceSummary,
) -> str:
    def format_monetary_values(amount_in_usd: float) -> str:
        return _format_dual_currency_values(
            amount_usd=amount_in_usd,
            usd_eur_exchange_rate=usd_eur_exchange_rate,
        )

    total_strategy_equity_usd: float = compute_total_strategy_equity_usd(
        total_collateral_usd=position_snapshot.total_collateral_usd,
        total_debt_usd=position_snapshot.total_debt_usd,
        assets=position_snapshot.assets,
    )
    aave_net_worth_usd: float = compute_aave_net_worth_usd(
        total_collateral_usd=position_snapshot.total_collateral_usd,
        total_debt_usd=position_snapshot.total_debt_usd,
    )
    total_wallet_usd: float = compute_position_total_wallet_usd(assets=position_snapshot.assets)
    weighted_net_apy: float = compute_position_weighted_net_apy(assets=position_snapshot.assets)

    supply_inventory_entries: list[AaveSentinelNotificationInventoryEntry] = [
        AaveSentinelNotificationInventoryEntry(
            asset_symbol=asset.symbol,
            asset_amount=asset.supply_amount,
            asset_value_usd=asset.supply_value_usd,
            asset_annual_percentage_yield=asset.supply_annual_percentage_yield,
        )
        for asset in position_snapshot.assets
        if asset.supply_amount > 0
    ]
    debt_inventory_entries: list[AaveSentinelNotificationInventoryEntry] = [
        AaveSentinelNotificationInventoryEntry(
            asset_symbol=asset.symbol,
            asset_amount=asset.debt_amount,
            asset_value_usd=asset.debt_value_usd,
            asset_annual_percentage_yield=asset.borrow_annual_percentage_yield,
        )
        for asset in position_snapshot.assets
        if asset.debt_amount > 0
    ]
    wallet_inventory_entries: list[AaveSentinelNotificationInventoryEntry] = [
        AaveSentinelNotificationInventoryEntry(
            asset_symbol=asset.symbol,
            asset_amount=asset.wallet_amount,
            asset_value_usd=asset.wallet_value_usd,
            asset_annual_percentage_yield=None,
        )
        for asset in position_snapshot.assets
        if asset.wallet_amount > 0
    ]

    supply_asset_rows: list[AaveSentinelNotificationInventoryRow] = _build_inventory_asset_rows(
        inventory_entries=supply_inventory_entries,
    )
    debt_asset_rows: list[AaveSentinelNotificationInventoryRow] = _build_inventory_asset_rows(
        inventory_entries=debt_inventory_entries,
    )
    wallet_asset_rows: list[AaveSentinelNotificationInventoryRow] = _build_inventory_asset_rows(
        inventory_entries=wallet_inventory_entries,
    )

    inventory_asset_rows: list[AaveSentinelNotificationInventoryRow] = (
        supply_asset_rows + debt_asset_rows + wallet_asset_rows
    )
    inventory_token_column_width: int = max(
        (
            [
                _telegram_monospace_display_width(inventory_asset_row.token_symbol)
                for inventory_asset_row in inventory_asset_rows
            ]
        ),
        default=0,
    )

    supply_section_lines: list[str] = _format_inventory_section_lines(
        section_emoji="📈",
        section_label="Collatéral",
        section_total_label=_format_dual_currency_values(
            amount_usd=position_snapshot.total_collateral_usd,
            usd_eur_exchange_rate=usd_eur_exchange_rate,
        ),
        inventory_asset_rows=supply_asset_rows,
        token_column_width=inventory_token_column_width,
    )
    if len(supply_inventory_entries) == 0:
        supply_section_lines.append("  <i>Aucun</i>")

    debt_section_lines: list[str] = _format_inventory_section_lines(
        section_emoji="📉",
        section_label="Dette",
        section_total_label=_format_dual_currency_values(
            amount_usd=position_snapshot.total_debt_usd,
            usd_eur_exchange_rate=usd_eur_exchange_rate,
        ),
        inventory_asset_rows=debt_asset_rows,
        token_column_width=inventory_token_column_width,
    )
    if len(debt_inventory_entries) == 0:
        debt_section_lines.append("  <i>Aucune</i>")

    wallet_section_lines: list[str] = _format_inventory_section_lines(
        section_emoji="💼",
        section_label="Wallet",
        section_total_label=_format_dual_currency_values(
            amount_usd=total_wallet_usd,
            usd_eur_exchange_rate=usd_eur_exchange_rate,
        ),
        inventory_asset_rows=wallet_asset_rows,
        token_column_width=inventory_token_column_width,
    )
    if len(wallet_inventory_entries) == 0:
        wallet_section_lines.append("  <i>Vide</i>")

    aave_positions_section_lines: list[str] = []
    aave_positions_section_lines.extend(supply_section_lines)
    aave_positions_section_lines.append("")
    aave_positions_section_lines.extend(debt_section_lines)
    aave_positions_section_lines.append("")
    aave_positions_section_lines.extend(wallet_section_lines)
    health_factor_indicator: str = resolve_health_factor_indicator(
        position_snapshot.health_factor,
    )

    account_section_lines: list[str] = [
        f"🏥 Santé : {health_factor_indicator} <code>{position_snapshot.health_factor:.2f}</code>",
        f"💎 Net Aave : <code>{format_monetary_values(aave_net_worth_usd)}</code>",
        f"💰 Net total : <code>{format_monetary_values(total_strategy_equity_usd)}</code>",
    ]
    account_section_lines.extend(
        _build_balance_sheet_section_lines(
            performance_summary=performance_summary,
            capital_flow_summary=capital_flow_summary,
            format_monetary_values=format_monetary_values,
        )
    )
    message_sections: list[str] = [
        build_telegram_section_block("Compte", account_section_lines),
    ]

    if position_snapshot.strategies:
        strategy_section_lines: list[str] = _build_strategies_section_lines(
            strategies=position_snapshot.strategies,
        )
    else:
        strategy_section_lines = ["  <i>Aucune stratégie en cours</i>"]
    message_sections.append(build_telegram_section_block("Stratégies", strategy_section_lines))

    message_sections.append(build_telegram_section_block("Positions AAVE", aave_positions_section_lines))

    performance_section_lines: list[str] = [
        f"📊 APY net actuel : <code>{format_percent(weighted_net_apy)}</code>",
        f"📥 Entrées : <code>{format_monetary_values(capital_flow_summary.total_inflow_usd)}</code>",
        f"📤 Sorties : <code>{format_monetary_values(capital_flow_summary.total_outflow_usd)}</code>",
        f"💼 Capital net : <code>{format_monetary_values(capital_flow_summary.net_capital_deployed_usd)}</code>",
        "",
        "🔎 Détail : /pnl",
    ]
    message_sections.append(build_telegram_section_block("Performance", performance_section_lines))

    return "\n".join(section for section in message_sections if section)

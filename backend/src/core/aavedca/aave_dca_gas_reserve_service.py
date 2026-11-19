from __future__ import annotations

from datetime import date

from src.configuration.config import settings
from src.core.aavedca.aave_dca_notification_service import dispatch_aave_dca_native_gas_shortfall_alert
from src.core.aavedca.aave_dca_structures import AaveDcaInsufficientNativeGasError, AaveDcaNativeGasRequirement
from src.core.aavedca.aave_dca_utils import compute_aave_dca_native_gas_requirement
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.logging.logger import get_application_logger
from src.persistence.models import AaveDcaStrategy

logger = get_application_logger(__name__)

_last_gas_shortfall_alert_date_by_strategy_identifier: dict[int, date] = {}


async def assess_aave_dca_native_gas_requirement(
        aave_executor: AaveExecutor,
        blockchain_network: BlockchainNetwork,
        order_count: int,
) -> AaveDcaNativeGasRequirement:
    max_fee_per_gas_wei: int = await aave_executor.fetch_max_fee_per_gas_wei(blockchain_network)
    wallet_balance_avax: float = await aave_executor.fetch_native_gas_balance_avax(blockchain_network)
    native_gas_requirement: AaveDcaNativeGasRequirement = compute_aave_dca_native_gas_requirement(
        order_count=order_count,
        max_fee_per_gas_wei=max_fee_per_gas_wei,
        wallet_balance_avax=wallet_balance_avax,
        minimum_reserve_avax=settings.AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX,
    )
    logger.debug(
        "[AAVEDCA][GASRESERVE][ASSESS] Native gas requirement — blockchain_network=%s order_count=%d max_fee_per_gas_wei=%d "
        "wallet_balance_avax=%.6f required_balance_avax=%.6f is_sufficient=%s",
        blockchain_network.value,
        order_count,
        max_fee_per_gas_wei,
        native_gas_requirement.wallet_balance_avax,
        native_gas_requirement.required_balance_avax,
        native_gas_requirement.is_sufficient,
    )
    return native_gas_requirement


async def ensure_aave_dca_native_gas_for_new_strategy(
        aave_executor: AaveExecutor,
        blockchain_network: BlockchainNetwork,
        order_count: int,
) -> None:
    native_gas_requirement: AaveDcaNativeGasRequirement = await assess_aave_dca_native_gas_requirement(
        aave_executor=aave_executor,
        blockchain_network=blockchain_network,
        order_count=order_count,
    )
    if not native_gas_requirement.is_sufficient:
        logger.info(
            "[AAVEDCA][GASRESERVE][GUARD] Strategy creation refused — wallet_balance_avax=%.6f required_balance_avax=%.6f "
            "missing_balance_avax=%.6f order_count=%d",
            native_gas_requirement.wallet_balance_avax,
            native_gas_requirement.required_balance_avax,
            native_gas_requirement.missing_balance_avax,
            order_count,
        )
        raise AaveDcaInsufficientNativeGasError(native_gas_requirement)

    logger.info(
        "[AAVEDCA][GASRESERVE][GUARD] Native gas sufficient for the new strategy — wallet_balance_avax=%.6f required_balance_avax=%.6f",
        native_gas_requirement.wallet_balance_avax,
        native_gas_requirement.required_balance_avax,
    )


async def alert_aave_dca_native_gas_shortfall(
        aave_executor: AaveExecutor,
        dca_strategy: AaveDcaStrategy,
        remaining_order_count: int,
) -> None:
    native_gas_requirement: AaveDcaNativeGasRequirement = await assess_aave_dca_native_gas_requirement(
        aave_executor=aave_executor,
        blockchain_network=BlockchainNetwork(dca_strategy.blockchain_network.lower()),
        order_count=remaining_order_count,
    )
    if native_gas_requirement.is_sufficient:
        return

    current_date: date = get_current_local_datetime().date()
    if _last_gas_shortfall_alert_date_by_strategy_identifier.get(dca_strategy.id) == current_date:
        logger.debug(
            "[AAVEDCA][GASRESERVE][ALERT] Gas shortfall already alerted today for strategy_id=%s",
            dca_strategy.id,
        )
        return

    _last_gas_shortfall_alert_date_by_strategy_identifier[dca_strategy.id] = current_date
    dispatch_aave_dca_native_gas_shortfall_alert(dca_strategy, native_gas_requirement)

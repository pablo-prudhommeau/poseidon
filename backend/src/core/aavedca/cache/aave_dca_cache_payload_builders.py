from __future__ import annotations

from src.api.http.api_schemas import AaveDcaStrategyPayload
from src.api.serializers import serialize_aave_dca_strategy
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_utils import run_awaitable_in_fresh_loop
from src.integrations.aave.aave_executor import AaveExecutor
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.database_session_manager import get_database_session

_aave_executor = AaveExecutor()


def build_aave_dca_strategies_payload() -> list[AaveDcaStrategyPayload]:
    return run_awaitable_in_fresh_loop(
        asynchronous_task=_fetch_dca_strategies_with_live_metrics(),
        debug_label="build_aave_dca_strategies_payload",
    )


async def _fetch_dca_strategies_with_live_metrics() -> list[AaveDcaStrategyPayload]:
    payloads: list[AaveDcaStrategyPayload] = []
    with get_database_session() as database_session:
        strategy_dao = AaveDcaStrategyDao(database_session)
        registered_strategies = strategy_dao.retrieve_all()
        for strategy in registered_strategies:
            live_metrics = await _aave_executor.get_live_metrics(
                chain=BlockchainNetwork(strategy.blockchain_network.lower()),
                asset_in_address=strategy.source_asset_address,
                asset_out_address=strategy.target_asset_address,
            )
            payloads.append(serialize_aave_dca_strategy(strategy, live_metrics))

    return payloads

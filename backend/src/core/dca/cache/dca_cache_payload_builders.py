from __future__ import annotations

from src.api.http.api_schemas import DcaStrategyPayload
from src.api.serializers import serialize_dca_strategy
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_utils import run_awaitable_in_fresh_loop
from src.integrations.aave.aave_executor import AaveExecutor
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.db import get_database_session

_aave_executor = AaveExecutor()


def build_dca_strategies_payload() -> list[DcaStrategyPayload]:
    return run_awaitable_in_fresh_loop(
        asynchronous_task=_fetch_dca_strategies_with_live_metrics(),
        debug_label="build_dca_strategies_payload",
    )


async def _fetch_dca_strategies_with_live_metrics() -> list[DcaStrategyPayload]:
    payloads: list[DcaStrategyPayload] = []
    with get_database_session() as database_session:
        strategy_dao = DcaStrategyDao(database_session)
        registered_strategies = strategy_dao.retrieve_all()
        for strategy in registered_strategies:
            live_metrics = await _aave_executor.get_live_metrics(
                chain=BlockchainNetwork(strategy.blockchain_network.lower()),
                asset_in_address=strategy.source_asset_address,
                asset_out_address=strategy.target_asset_address,
            )
            payloads.append(serialize_dca_strategy(strategy, live_metrics))

    return payloads

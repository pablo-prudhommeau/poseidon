from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.solana.solana_mint_freeze_authority_helpers import (
    is_solana_mint_blocked_by_freeze_authority_snapshot,
)
from src.integrations.blockchain.solana.solana_mint_freeze_authority_service import (
    resolve_solana_mint_freeze_authority_snapshots_batch,
)
from src.logging.logger import get_application_logger
from src.migrations.operations.migrations_operations_structures import HoneypotShadowingVerdictBackfillResult
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict

logger = get_application_logger(__name__)


def reclassify_profitable_shadowing_verdicts_with_active_freeze_authority(
        database_session: Session,
) -> HoneypotShadowingVerdictBackfillResult:
    candidate_verdicts = list(
        database_session.scalars(
            select(TradingShadowingVerdict)
            .options(joinedload(TradingShadowingVerdict.probe))
            .join(TradingShadowingProbe)
            .where(TradingShadowingVerdict.exit_reason.in_(("TAKE_PROFIT_2", "LETHARGIC")))
            .where(TradingShadowingVerdict.is_profitable.is_(True))
            .where(TradingShadowingProbe.blockchain_network == BlockchainNetwork.SOLANA.value),
        ).unique().all(),
    )

    if not candidate_verdicts:
        logger.info("[MIGRATION][OPERATIONS][HONEYPOT] No profitable Solana verdicts to inspect")
        return HoneypotShadowingVerdictBackfillResult(
            candidate_verdict_count=0,
            reclassified_verdict_count=0,
        )

    mint_addresses: list[str] = []
    seen_mint_addresses: set[str] = set()
    for verdict in candidate_verdicts:
        probe = verdict.probe
        normalized_mint_address = probe.token_address.strip()
        if not normalized_mint_address or normalized_mint_address in seen_mint_addresses:
            continue
        seen_mint_addresses.add(normalized_mint_address)
        mint_addresses.append(normalized_mint_address)

    freeze_authority_snapshots = resolve_solana_mint_freeze_authority_snapshots_batch(
        mint_addresses=mint_addresses,
    )
    snapshots_by_mint_address = {
        snapshot.mint_address: snapshot for snapshot in freeze_authority_snapshots
    }

    reclassified_verdict_count = 0
    for verdict in candidate_verdicts:
        probe = verdict.probe
        snapshot = snapshots_by_mint_address.get(probe.token_address.strip())
        if snapshot is None:
            continue
        if not is_solana_mint_blocked_by_freeze_authority_snapshot(snapshot):
            continue

        verdict.exit_reason = "HONEYPOT"
        verdict.realized_pnl_percentage = -100.0
        verdict.realized_pnl_usd = -probe.order_notional_value_usd
        verdict.is_profitable = False
        verdict.take_profit_tier_2_hit_at = None
        reclassified_verdict_count += 1

    logger.info(
        "[MIGRATION][OPERATIONS][HONEYPOT] Reclassified %d / %d profitable Solana verdicts as HONEYPOT",
        reclassified_verdict_count,
        len(candidate_verdicts),
    )
    return HoneypotShadowingVerdictBackfillResult(
        candidate_verdict_count=len(candidate_verdicts),
        reclassified_verdict_count=reclassified_verdict_count,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingVerdictChronicleCortexModelRollout
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingCortexModelManifest


@dataclass(frozen=True)
class _CortexManifestSnapshot:
    activated_at_milliseconds: int
    model_version: str
    feature_set_version: str
    training_record_count: int
    validation_record_count: int
    success_probability_accuracy: float
    is_active: bool
    created_at: datetime


def _format_compact_record_count(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def _format_cortex_rollout_chronicle_label(
        manifest: _CortexManifestSnapshot,
        previous_feature_set_version: str | None,
) -> str:
    model_token = manifest.model_version
    feature_set_token = manifest.feature_set_version
    if len(feature_set_token) > 18:
        feature_set_token = f"{feature_set_token[:15]}..."
    train_count = _format_compact_record_count(manifest.training_record_count)
    validation_count = _format_compact_record_count(manifest.validation_record_count)
    accuracy_percent = int(round(manifest.success_probability_accuracy * 100))
    label = f"Cortex · model {model_token} · features {feature_set_token} · train/val {train_count}/{validation_count} · acc {accuracy_percent}%"
    if previous_feature_set_version and manifest.feature_set_version != previous_feature_set_version:
        label = f"{label} · feature set changed"
    return label


def _load_cortex_manifest_snapshots(
        from_datetime: datetime,
        to_datetime: datetime,
) -> list[_CortexManifestSnapshot]:
    with get_database_session() as session:
        manifests = session.execute(
            select(TradingCortexModelManifest)
            .where(TradingCortexModelManifest.created_at >= from_datetime)
            .where(TradingCortexModelManifest.created_at <= to_datetime)
            .order_by(TradingCortexModelManifest.created_at.asc())
        ).scalars().all()
        return [
            _CortexManifestSnapshot(
                activated_at_milliseconds=int(manifest.created_at.timestamp() * 1000),
                model_version=manifest.model_version,
                feature_set_version=manifest.feature_set_version,
                training_record_count=manifest.training_record_count,
                validation_record_count=manifest.validation_record_count,
                success_probability_accuracy=manifest.success_probability_accuracy,
                is_active=manifest.is_active,
                created_at=manifest.created_at,
            )
            for manifest in manifests
        ]


def load_cortex_model_rollouts_for_chronicle(
        from_datetime: datetime,
        to_datetime: datetime,
) -> list[TradingShadowingVerdictChronicleCortexModelRollout]:
    rollouts: list[TradingShadowingVerdictChronicleCortexModelRollout] = []
    previous_feature_set_version: str | None = None
    for manifest in _load_cortex_manifest_snapshots(from_datetime, to_datetime):
        rollouts.append(
            TradingShadowingVerdictChronicleCortexModelRollout(
                activated_at_milliseconds=manifest.activated_at_milliseconds,
                model_version=manifest.model_version,
                feature_set_version=manifest.feature_set_version,
                training_record_count=manifest.training_record_count,
                validation_record_count=manifest.validation_record_count,
                success_probability_accuracy=manifest.success_probability_accuracy,
                is_active=manifest.is_active,
                label=_format_cortex_rollout_chronicle_label(manifest, previous_feature_set_version),
            )
        )
        previous_feature_set_version = manifest.feature_set_version
    return rollouts

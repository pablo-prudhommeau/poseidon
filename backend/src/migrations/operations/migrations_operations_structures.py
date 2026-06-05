from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HoneypotShadowingVerdictBackfillResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    candidate_verdict_count: int
    reclassified_verdict_count: int

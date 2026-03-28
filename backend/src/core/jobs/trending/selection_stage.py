from __future__ import annotations

from typing import List, Set, Tuple

from src.configuration.config import settings
from src.core.gates.trending_scoring import filter_candidates_by_quality
from src.core.structures.structures import Candidate
from src.core.utils.trending_utils import (
    filter_strict,
    soft_fill,
    fetch_trending_candidates_sync,
    is_address_in_open_positions,
)
from src.logging.logger import get_logger
from src.persistence.dao.positions import retrieve_open_positions
from src.persistence.db import _session

log = get_logger(__name__)


class CandidateSelectionStage:
    def __init__(self) -> None:
        self.interval: str = settings.TREND_INTERVAL.lower()
        self.page_size: int = settings.TREND_PAGE_SIZE
        self.max_results: int = settings.TREND_MAX_RESULTS

        self.minimum_volume_5m_usd: float = settings.TREND_MIN_VOL5M_USD
        self.minimum_volume_1h_usd: float = settings.TREND_MIN_VOL1H_USD
        self.minimum_volume_6h_usd: float = settings.TREND_MIN_VOL6H_USD
        self.minimum_volume_24h_usd: float = settings.TREND_MIN_VOL24H_USD

        self.minimum_liquidity_usd: float = settings.TREND_MIN_LIQ_USD
        self.minimum_percent_5m: float = settings.TREND_MIN_PCT_5M
        self.minimum_percent_1h: float = settings.TREND_MIN_PCT_1H
        self.minimum_percent_6h: float = settings.TREND_MIN_PCT_6H
        self.minimum_percent_24h: float = settings.TREND_MIN_PCT_24H

        self.soft_fill_minimum: int = settings.TREND_SOFT_FILL_MIN
        self.soft_fill_sort_key: str = settings.TREND_SOFT_FILL_SORT

    def fetch_candidates_raw(self) -> List[Candidate]:
        rows = fetch_trending_candidates_sync()
        if not rows:
            log.info("[TREND][FETCH] 0 candidates.")
        return rows

    def apply_hard_filters(self, raw_rows: List[Candidate]) -> List[Candidate]:
        kept, rejected_counts = filter_strict(
            raw_rows,
            interval=self.interval,
            volume_threshold_5m=self.minimum_volume_5m_usd,
            volume_threshold_1h=self.minimum_volume_1h_usd,
            volume_threshold_6h=self.minimum_volume_6h_usd,
            volume_threshold_24h=self.minimum_volume_24h_usd,
            minimum_liquidity_usd=self.minimum_liquidity_usd,
            percent_threshold_5m=self.minimum_percent_5m,
            percent_threshold_1h=self.minimum_percent_1h,
            percent_threshold_6h=self.minimum_percent_6h,
            percent_threshold_24h=self.minimum_percent_24h,
            maximum_results=self.max_results,
        )
        log.info("[TREND][FILTER][STRICT] kept=%d rejected=%s", len(kept), rejected_counts)
        return kept

    def apply_soft_fill(self, raw_rows: List[Candidate], kept_rows: List[Candidate]) -> List[Candidate]:
        need_minimum = max(self.soft_fill_minimum, len(kept_rows))
        filled = soft_fill(
            candidate_universe=raw_rows,
            retained_candidates=kept_rows,
            minimum_required_candidates=need_minimum,
            minimum_liquidity_usd=self.minimum_liquidity_usd,
            sort_key=self.soft_fill_sort_key,
        )
        log.debug("[TREND][FILTER][SOFT_FILL] result=%d", len(filled))
        return filled

    def apply_quality_gate(self, kept_rows: List[Candidate]) -> List[Candidate]:
        result = filter_candidates_by_quality(kept_rows)
        if not result:
            log.info("[TREND][GATE][QUALITY] 0 candidates after gate #1.")
        return result

    def order_and_truncate(self, candidates: List[Candidate]) -> List[Candidate]:
        sort_key = self.soft_fill_sort_key if self.soft_fill_sort_key in {"vol24h", "liqUsd"} else "vol24h"
        if sort_key == "liqUsd":
            candidates.sort(key=lambda c: float(c.dexscreener_token_information.liquidity.usd), reverse=True)
        else:
            candidates.sort(key=lambda c: float(c.dexscreener_token_information.volume.h24), reverse=True)
        return candidates[: self.max_results]

    def _open_positions_sets(self) -> Tuple[Set[str], Set[str]]:
        with _session() as db:
            positions = retrieve_open_positions(db)
            open_symbols = {(p.token_symbol or "").upper() for p in positions if p.token_symbol}
            open_addresses: Set[str] = {p.token_address for p in positions if p.token_address}
            return open_symbols, open_addresses

    def deduplicate_open_positions(self, candidates: List[Candidate]) -> List[Candidate]:
        open_symbols, open_addresses = self._open_positions_sets()
        pruned: List[Candidate] = []
        for candidate in candidates:
            symbol_upper = candidate.dexscreener_token_information.base_token.symbol.upper()
            if symbol_upper in open_symbols or is_address_in_open_positions(
                    candidate.dexscreener_token_information.base_token.address, open_addresses):
                log.debug("[TREND][DEDUP] Skip already open %s (%s).",
                          candidate.dexscreener_token_information.base_token.symbol,
                          candidate.dexscreener_token_information.base_token.address)
                continue
            pruned.append(candidate)
        if not pruned:
            log.debug("[TREND][DEDUP] 0 candidates after de-duplication.")
        return pruned

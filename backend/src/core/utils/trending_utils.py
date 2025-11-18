from __future__ import annotations

import asyncio
import math
import threading
from datetime import timedelta
from typing import (
    Awaitable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Final,
    TypeVar,
)

from sqlalchemy import select

from src.configuration.config import settings
from src.core.structures.structures import Candidate, ScoreComponents, Token
from src.core.utils.date_utils import timezone_now
from src.core.utils.format_utils import _tail, _format
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list_sync
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation, \
    DexscreenerTransactionActivity
from src.logging.logger import get_logger
from src.persistence.db import _session
from src.persistence.models import Trade

log = get_logger(__name__)

RejectionCounts = Dict[str, int]

_SOFT_SORT_KEYS: Final[Set[str]] = {"vol5m", "vol1h", "vol6h", "vol24h", "liqUsd"}

U = TypeVar("U")


def _is_number(value: object) -> bool:
    """Return True if value can be interpreted as a finite float."""
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _passes_percent_thresholds(
        candidate: Candidate,
        interval: str,
        th5: float,
        th1: float,
        th6: float,
        th24: float,
) -> bool:
    pct_5m = candidate.dexscreener_token_information.price_change.m5
    pct_1h = candidate.dexscreener_token_information.price_change.h1
    pct_6h = candidate.dexscreener_token_information.price_change.h6
    pct_24h = candidate.dexscreener_token_information.price_change.h1

    if interval == "5m":
        return (pct_5m is not None and pct_5m >= th5) or (pct_24h is not None and pct_24h >= th24)
    if interval == "1h":
        return (pct_1h is not None and pct_1h >= th1) or (pct_24h is not None and pct_24h >= th24)
    if interval == "6h":
        return (pct_6h is not None and pct_6h >= th6) or (pct_24h is not None and pct_24h >= th24)
    return pct_24h is not None and pct_24h >= th24


def _passes_volume_thresholds(
        candidate: Candidate,
        interval: str,
        th5: float,
        th1: float,
        th6: float,
        th24: float,
) -> bool:
    vol_5m = candidate.dexscreener_token_information.volume.m5
    vol_1h = candidate.dexscreener_token_information.volume.h1
    vol_6h = candidate.dexscreener_token_information.volume.h6
    vol_24h = candidate.dexscreener_token_information.volume.h24

    if interval == "5m":
        return (vol_5m is not None and vol_5m >= th5) or (vol_24h is not None and vol_24h >= th24)
    if interval == "1h":
        return (vol_1h is not None and vol_1h >= th1) or (vol_24h is not None and vol_24h >= th24)
    if interval == "6h":
        return (vol_6h is not None and vol_6h >= th6) or (vol_24h is not None and vol_24h >= th24)
    return vol_24h is not None and vol_24h >= th24

def _has_valid_intraday_bars(candidate: Candidate) -> bool:
    return (
            _is_number(candidate.dexscreener_token_information.price_change.m5)
            and _is_number(candidate.dexscreener_token_information.price_change.h1)
            and _is_number(candidate.dexscreener_token_information.price_change.h6)
            and _is_number(candidate.dexscreener_token_information.price_change.h24)
    )


def _momentum_ok(p5: Optional[float], p1: Optional[float], p6: Optional[float], p24: Optional[float]) -> bool:
    """
    Conservative sanity checks against spiky/choppy momentum using caps on 5m and 1h.
    """
    cap_m5 = float(settings.DEXSCREENER_MAX_ABS_M5_PCT)
    cap_h1 = float(settings.DEXSCREENER_MAX_ABS_H1_PCT)
    cap_h6 = float(settings.DEXSCREENER_MAX_ABS_H6_PCT)
    cap_h24 = float(settings.DEXSCREENER_MAX_ABS_H24_PCT)
    if p5 is not None and abs(p5) > cap_m5:
        return False
    if p1 is not None and abs(p1) > cap_h1:
        return False
    if p6 is not None and abs(p6) > cap_h6:
        return False
    if p24 is not None and abs(p24) > cap_h24:
        return False
    return True


def _candidate_from_dexscreener_token_information(
        dexscreenerTokenInformation: DexscreenerTokenInformation) -> Candidate:
    return Candidate(
        quality_score=0.0,
        statistics_score=0.0,
        entry_score=0.0,
        score_final=0.0,
        score_components=ScoreComponents(
            quality_score=0.0,
            statistics_score=0.0,
            entry_score=0.0,
        ),
        ai_quality_delta=0.0,
        ai_buy_probability=0.0,
        dexscreener_token_information=dexscreenerTokenInformation,
        token=Token(
            symbol=dexscreenerTokenInformation.base_token.symbol,
            chain=dexscreenerTokenInformation.chain_id,
            tokenAddress=dexscreenerTokenInformation.base_token.address,
            pairAddress=dexscreenerTokenInformation.pair_address
        ),
    )


def _get_candidate_sort_value(candidate: Candidate, key: str) -> float:
    """
    Map legacy sort keys ('vol24h' / 'liqUsd') to strongly-typed Candidate attributes.

    We avoid getattr() on purpose to keep attribute access explicit and auditable.
    """
    if key == "liqUsd":
        return candidate.dexscreener_token_information.liquidity.usd
    return candidate.dexscreener_token_information.volume.h24


def _buy_sell_score(txns: DexscreenerTransactionActivity) -> float:
    """Return the fraction of buys over total transactions in [0.0..1.0]."""
    bucket = txns.h1 or txns.h24
    buys = bucket.buys
    sells = bucket.sells
    total = buys + sells
    return 0.5 if total <= 0 else buys / total


def filter_strict(
        candidates: List[Candidate],
        *,
        interval: str,
        volth5: float,
        volth1: float,
        volth6: float,
        volth24: float,
        min_liq_usd: float,
        pctth5: float,
        pctth1: float,
        pctth6: float,
        pctth24: float,
        max_results: int,
) -> Tuple[List[Candidate], RejectionCounts]:
    """
    Hard filters for trending candidates; returns (kept, rejection_counts).
    Applies minimal volume/liquidity floors and interval-specific momentum gates.
    """
    kept: List[Candidate] = []
    rejected: RejectionCounts = {"excl": 0, "lowvol": 0, "lowliq": 0, "lowpct": 0}

    for candidate in candidates:
        symbol = candidate.dexscreener_token_information.base_token.symbol
        liquidity_usd = candidate.dexscreener_token_information.liquidity.usd

        if not _passes_volume_thresholds(candidate, interval, volth5, volth1, volth6, volth24):
            log.debug("[TREND][FILTER][STRICT][REJECT] %s — fails vol thresholds for %s", symbol, interval)
            rejected["lowvol"] += 1
            continue

        if liquidity_usd < min_liq_usd:
            log.debug("[TREND][FILTER][STRICT][REJECT] %s — liq=%.0f<%.0f", symbol, liquidity_usd, min_liq_usd)
            rejected["lowliq"] += 1
            continue

        if not _passes_percent_thresholds(candidate, interval, pctth5, pctth1, pctth6, pctth24):
            log.debug("[TREND][FILTER][STRICT][REJECT] %s — fails pct thresholds for %s", symbol, interval)
            rejected["lowpct"] += 1
            continue

        kept.append(candidate)
        if len(kept) >= max_results:
            log.debug("[TREND][FILTER][STRICT] Reached max results %d", max_results)
            break

    for candidate in kept:
        symbol = candidate.dexscreener_token_information.base_token.symbol
        short_address = _tail(candidate.dexscreener_token_information.base_token.address)

        volume_5m_usd = candidate.dexscreener_token_information.volume.m5
        volume_1h_usd = candidate.dexscreener_token_information.volume.h1
        volume_6h_usd = candidate.dexscreener_token_information.volume.h6
        volume_24h_usd = candidate.dexscreener_token_information.volume.h24

        liquidity_usd = candidate.dexscreener_token_information.liquidity.usd

        p5 = candidate.dexscreener_token_information.price_change.m5
        p1 = candidate.dexscreener_token_information.price_change.h1
        p6 = candidate.dexscreener_token_information.price_change.h6
        p24 = candidate.dexscreener_token_information.price_change.h24

        via = "24h"
        if interval == "5m" and p5 is not None and p5 >= pctth5:
            via = "5m"
        elif interval == "1h" and p1 is not None and p1 >= pctth1:
            via = "1h"
        elif interval == "6h" and p6 is not None and p6 >= pctth6:
            via = "6h"
        elif p24 is not None and p24 >= pctth24:
            via = "24h"

        log.debug(
            "[TREND][FILTER][STRICT][KEEP] %s (%s) — vol5m=%.0f≥%.0f vol1h=%.0f≥%.0f vol6h=%.0f≥%.0f vol24h=%.0f≥%.0f liq=%.0f≥%.0f p5=%s(th=%.2f) p1=%s(th=%.2f) p6=%s(th=%.2f) p24=%s(th=%.2f) via=%s",
            symbol,
            short_address,
            volume_5m_usd,
            volth5,
            volume_1h_usd,
            volth1,
            volume_6h_usd,
            volth6,
            volume_24h_usd,
            volth24,
            liquidity_usd,
            min_liq_usd,
            _format(p5),
            pctth5,
            _format(p1),
            pctth1,
            _format(p6),
            pctth6,
            _format(p24),
            pctth24,
            via,
        )

    return kept, rejected


def soft_fill(
        universe: List[Candidate],
        kept: List[Candidate],
        *,
        need_min: int,
        min_liq_usd: float,
        sort_key: str,
) -> List[Candidate]:
    if need_min <= 0 or len(kept) >= need_min:
        return kept

    kept_addresses: Set[str] = {row.dexscreener_token_information.base_token.address for row in kept if
                                row.dexscreener_token_information.base_token.address}
    pool: List[Candidate] = []
    for row in universe:
        address = row.dexscreener_token_information.base_token.address
        if address and address in kept_addresses:
            continue

        vol5 = row.dexscreener_token_information.volume.m5
        vol1 = row.dexscreener_token_information.volume.h1
        vol6 = row.dexscreener_token_information.volume.h6
        vol24 = row.dexscreener_token_information.volume.h24
        if (vol5 is None
                or vol1 is None
                or vol6 is None
                or vol24 is None
                or (vol5 < 0.0 and vol1 < 0.0 and vol6 < 0.0 and vol24 < 0.0)
        ):
            continue

        p5 = row.dexscreener_token_information.price_change.m5
        p1 = row.dexscreener_token_information.price_change.h1
        p6 = row.dexscreener_token_information.price_change.h6
        p24 = row.dexscreener_token_information.price_change.h24
        if (p1 is not None
                and p5 is not None
                and p6 is not None
                and p24 is not None
                and (p1 < 0.0 and p24 < 0.0 and p5 < 0.0 and p6 < 0.0)
        ):
            continue

        pool.append(row)

    key = sort_key if sort_key in _SOFT_SORT_KEYS else "vol24h"
    pool.sort(key=lambda c: _get_candidate_sort_value(c, key), reverse=True)

    for row in pool:
        if len(kept) >= need_min:
            break
        log.debug(
            "[TREND][FILTER][SOFT_FILL][KEEP] %s — vol=%.0f liq=%.0f p5=%s p1=%s p6=%s p24=%s",
            row.dexscreener_token_information.base_token.symbol,
            row.dexscreener_token_information.volume.h24,
            row.dexscreener_token_information.liquidity.usd,
            row.dexscreener_token_information.price_change.m5,
            row.dexscreener_token_information.price_change.h1,
            row.dexscreener_token_information.price_change.h6,
            row.dexscreener_token_information.price_change.h24,
        )
        kept.append(row)
        if row.dexscreener_token_information.base_token.address:
            kept_addresses.add(row.dexscreener_token_information.base_token.address)

    return kept


def recently_traded(address: str, minutes: int = 45) -> bool:
    """
    Return True if a trade for this address exists more recently than `minutes`.
    """
    if not address:
        return False

    with _session() as db:
        query = (
            select(Trade)
            .where(Trade.tokenAddress == address)
            .order_by(Trade.created_at.desc())
        )
        trade = db.execute(query).scalars().first()
        if not trade:
            return False

        now = timezone_now()
        created = trade.created_at.astimezone()
        return (now - created) < timedelta(minutes=minutes)


def preload_best_prices(candidates: List[Candidate]) -> List[DexscreenerTokenInformation]:
    """
    Deduplicate and fetch best prices for a list of addresses (address → price).
    Keeps input order of first occurrence.
    """
    if not candidates:
        return []
    deduped_tokens_in_order: List[Token] = []
    seen_keys: Set[Tuple[str, str, str, str]] = set()
    for candidate in candidates:
        key = (
            candidate.dexscreener_token_information.base_token.symbol or "",
            candidate.dexscreener_token_information.chain_id or "",
            candidate.dexscreener_token_information.base_token.address or "",
            candidate.dexscreener_token_information.pair_address or "",
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_tokens_in_order.append(
            Token(
                symbol=candidate.dexscreener_token_information.base_token.symbol,
                chain=candidate.dexscreener_token_information.chain_id,
                tokenAddress=candidate.dexscreener_token_information.base_token.address,
                pairAddress=candidate.dexscreener_token_information.pair_address
            )
        )
    if not deduped_tokens_in_order:
        return []
    return fetch_dexscreener_token_information_list_sync(deduped_tokens_in_order)


def _price_from(dexscreener_token_information_list: List[DexscreenerTokenInformation], candidate: Candidate) -> Optional[float]:
    """
    Fetch a price from a list of TokenPrice objects matching the candidate's chain, symbol, token address and pair address.
    """
    for token_information in dexscreener_token_information_list:
        if (
                token_information.base_token.symbol == candidate.dexscreener_token_information.base_token.symbol
                and token_information.chain_id == candidate.dexscreener_token_information.chain_id
                and token_information.base_token.address == candidate.dexscreener_token_information.base_token.address
                and token_information.pair_address == candidate.dexscreener_token_information.pair_address
        ):
            return token_information.price_usd
    return None


def _run_awaitable_in_fresh_loop(task: Awaitable[U], *, debug_label: str = "") -> U:
    """
    Run an awaitable safely in a dedicated event loop.

    Behavior:
      - If there's no running loop: use asyncio.run().
      - If the loop is closed OR already running (e.g. notebooks, frameworks):
        spin up a brand-new loop in a separate thread and run the task there.

    This avoids 'Event loop is closed' and
    'asyncio.run() cannot be called from a running event loop'.
    """
    try:
        return asyncio.run(task)
    except RuntimeError as exc:
        message = str(exc)
        if ("Event loop is closed" not in message) and ("cannot be called from a running event loop" not in message):
            raise

        label = debug_label or "task"
        log.debug("[TREND][ASYNC] loop issue detected (%s: %s); running in a fresh thread+loop.", label, message)

        result_holder: Dict[str, U] = {}
        error_holder: Dict[str, BaseException] = {}

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result_holder["result"] = loop.run_until_complete(task)
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass  # best-effort cleanup
            except BaseException as error:
                error_holder["error"] = error
            finally:
                try:
                    asyncio.set_event_loop(None)
                except Exception:
                    pass
                loop.close()

        thread = threading.Thread(target=_runner, name=f"fresh-loop-{label}", daemon=True)
        thread.start()
        thread.join()

        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder["result"]


def _fetch_trending_candidates_sync() -> List[Candidate]:
    """
    Synchronously fetch trending candidates from Dexscreener by running the async
    client in a safe, dedicated loop, then convert to :class:`Candidate`.
    """
    from src.integrations.dexscreener.dexscreener_client import fetch_trending_candidates

    rows: List[DexscreenerTokenInformation] = _run_awaitable_in_fresh_loop(
        fetch_trending_candidates(),
        debug_label="fetch_trending_candidates",
    )
    candidates: List[Candidate] = [_candidate_from_dexscreener_token_information(r) for r in rows]
    log.info("[TREND][FETCH] converted %d normalized rows into Candidate objects.", len(candidates))
    return candidates


def _is_address_in_open_positions(candidate_address: str, open_addresses: Set[str]) -> bool:
    """Return True if the candidate address is a currently open position."""
    return bool(candidate_address) and candidate_address in open_addresses

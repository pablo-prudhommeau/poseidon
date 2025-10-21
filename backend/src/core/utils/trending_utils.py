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
from src.core.structures.structures import Candidate, TransactionSummary, ScoreComponents, TransactionBucket, \
    Token
from src.core.utils.date_utils import timezone_now
from src.core.utils.format_utils import _tail, _format, _age_hours
from src.integrations.dexscreener.dexscreener_client import fetch_price_by_tokens_sync
from src.integrations.dexscreener.dexscreener_structures import NormalizedRow, TransactionActivity, TransactionCount, \
    TokenPrice
from src.logging.logger import get_logger
from src.persistence.db import _session
from src.persistence.models import Trade

log = get_logger(__name__)

RejectionCounts = Dict[str, int]

_SOFT_SORT_KEYS: Final[Set[str]] = {"vol24h", "liqUsd"}

U = TypeVar("U")


def _is_number(value: object) -> bool:
    """Return True if value can be interpreted as a finite float."""
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _passes_thresholds(
        item: Candidate,
        interval: str,
        th5: float,
        th1: float,
        th24: float,
) -> bool:
    """
    Check percent-change thresholds depending on the selected interval.

    Rules:
      - "5m": pass if pct_5m ≥ th5 OR pct_24h ≥ th24
      - "1h": pass if pct_1h ≥ th1 OR pct_24h ≥ th24
      - else: pass if pct_24h ≥ th24
    """
    pct_5m = item.percent_5m
    pct_1h = item.percent_1h
    pct_24h = item.percent_24h

    if interval == "5m":
        return (pct_5m is not None and pct_5m >= th5) or (pct_24h is not None and pct_24h >= th24)
    if interval == "1h":
        return (pct_1h is not None and pct_1h >= th1) or (pct_24h is not None and pct_24h >= th24)
    return pct_24h is not None and pct_24h >= th24


def _has_valid_intraday_bars(candidate: Candidate) -> bool:
    """
    True if both pct5m and pct1h are numeric (proxy for fresh intraday OHLCV).
    Note: despite the historical name, this checks percentage deltas.
    """
    return _is_number(candidate.percent_5m) and _is_number(candidate.percent_1h)


def _momentum_ok(p5: Optional[float], p1: Optional[float], p24: Optional[float]) -> bool:
    """
    Conservative sanity checks against spiky/choppy momentum using caps on 5m and 1h.
    """
    cap_m5 = float(settings.DEXSCREENER_MAX_ABS_M5_PCT)
    cap_h1 = float(settings.DEXSCREENER_MAX_ABS_H1_PCT)
    cap_h24 = float(settings.DEXSCREENER_MAX_ABS_H24_PCT)
    if p5 is not None and abs(p5) > cap_m5:
        return False
    if p1 is not None and abs(p1) > cap_h1:
        return False
    if p24 is not None and abs(p24) > cap_h24:
        return False
    return True


def _make_transaction_bucket(source: Optional[TransactionCount]) -> TransactionBucket:
    """
    Convert a Dexscreener TransactionCount into a core TransactionBucket.
    Missing input yields an empty bucket (0.0 / 0.0).
    """
    bucket = TransactionBucket()
    if source is None:
        bucket.buys = 0.0
        bucket.sells = 0.0
        return bucket

    # Convert to float for downstream computations (ratios, etc.)
    bucket.buys = float(source.buys)
    bucket.sells = float(source.sells)
    return bucket


def _make_transaction_summary(activity: Optional[TransactionActivity]) -> TransactionSummary:
    """
    Convert a Dexscreener TransactionActivity into the core TransactionSummary.
    Always returns a fully-formed summary object with all windows present.
    """
    summary = TransactionSummary()
    if activity is None:
        summary.m5 = _make_transaction_bucket(None)
        summary.h1 = _make_transaction_bucket(None)
        summary.h6 = _make_transaction_bucket(None)
        summary.h24 = _make_transaction_bucket(None)
        return summary

    summary.m5 = _make_transaction_bucket(activity.m5)
    summary.h1 = _make_transaction_bucket(activity.h1)
    summary.h6 = _make_transaction_bucket(activity.h6)
    summary.h24 = _make_transaction_bucket(activity.h24)
    return summary


def _candidate_from_normalized_row(row: NormalizedRow) -> Candidate:
    """
    Build a :class:`Candidate` from a :class:`NormalizedRow` without resorting to
    getattr() or dict-style access. We only include keys that are genuinely present.
    """
    txns_summary = _make_transaction_summary(row.txns)
    return Candidate(
        symbol=row.symbol,
        token_address=row.tokenAddress,
        pair_address=row.pairAddress,
        chain_name=row.chain,
        price_usd=row.priceUsd,
        price_native=row.priceNative,
        percent_5m=row.pct5m,
        percent_1h=row.pct1h,
        percent_24h=row.pct24h,
        volume_24h_usd=row.vol24h,
        liquidity_usd=row.liqUsd,
        pair_created_at_epoch_seconds=row.pairCreatedAt,
        txns=txns_summary,
        token_age_hours=_age_hours(row.pairCreatedAt),
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
        ai_buy_probability=0.0
    )


def _get_candidate_sort_value(candidate: Candidate, key: str) -> float:
    """
    Map legacy sort keys ('vol24h' / 'liqUsd') to strongly-typed Candidate attributes.

    We avoid getattr() on purpose to keep attribute access explicit and auditable.
    """
    if key == "liqUsd":
        return candidate.liquidity_usd
    return candidate.volume_24h_usd


def _buy_sell_score(txns: TransactionSummary) -> float:
    """Return the fraction of buys over total transactions in [0.0..1.0]."""
    bucket = txns.h1 or txns.h24
    buys = bucket.buys
    sells = bucket.sells
    total = buys + sells
    return 0.5 if total <= 0 else buys / total


def filter_strict(
        rows: List[Candidate],
        *,
        interval: str,
        min_vol_usd: float,
        min_liq_usd: float,
        th5: float,
        th1: float,
        th24: float,
        max_results: int,
) -> Tuple[List[Candidate], RejectionCounts]:
    """
    Hard filters for trending candidates; returns (kept, rejection_counts).
    Applies minimal volume/liquidity floors and interval-specific momentum gates.
    """
    kept: List[Candidate] = []
    rejected: RejectionCounts = {"excl": 0, "lowvol": 0, "lowliq": 0, "lowpct": 0}

    for item in rows:
        symbol = item.symbol
        volume_24h_usd = item.volume_24h_usd
        liquidity_usd = item.liquidity_usd

        if volume_24h_usd < min_vol_usd:
            log.debug("[TREND][FILTER][STRICT][REJECT] %s — vol=%.0f<%.0f", symbol, volume_24h_usd, min_vol_usd)
            rejected["lowvol"] += 1
            continue

        if liquidity_usd < min_liq_usd:
            log.debug("[TREND][FILTER][STRICT][REJECT] %s — liq=%.0f<%.0f", symbol, liquidity_usd, min_liq_usd)
            rejected["lowliq"] += 1
            continue

        if not _passes_thresholds(item, interval, th5, th1, th24):
            log.debug("[TREND][FILTER][STRICT][REJECT] %s — fails pct thresholds for %s", symbol, interval)
            rejected["lowpct"] += 1
            continue

        kept.append(item)
        if len(kept) >= max_results:
            log.debug("[TREND][FILTER][STRICT] Reached max results %d", max_results)
            break

    # Verbose context for kept rows
    for item in kept:
        symbol = item.symbol
        short_address = _tail(item.token_address)
        volume_24h_usd = item.volume_24h_usd
        liquidity_usd = item.liquidity_usd
        p5 = item.percent_5m
        p1 = item.percent_1h
        p24 = item.percent_24h

        via = "24h"
        if interval == "5m" and p5 is not None and p5 >= th5:
            via = "5m"
        elif interval == "1h" and p1 is not None and p1 >= th1:
            via = "1h"
        elif p24 is not None and p24 >= th24:
            via = "24h"

        log.debug(
            "[TREND][FILTER][STRICT][KEEP] %s (%s) — vol=%.0f≥%.0f liq=%.0f≥%.0f p5=%s(th=%.2f) p1=%s(th=%.2f) p24=%s(th=%.2f) via=%s",
            symbol,
            short_address,
            volume_24h_usd,
            min_vol_usd,
            liquidity_usd,
            min_liq_usd,
            _format(p5),
            th5,
            _format(p1),
            th1,
            _format(p24),
            th24,
            via,
        )

    return kept, rejected


def soft_fill(
        universe: List[Candidate],
        kept: List[Candidate],
        *,
        need_min: int,
        min_vol_usd: float,
        min_liq_usd: float,
        sort_key: str,
) -> List[Candidate]:
    """
    If needed, top up the kept list using a looser pool sorted by a given key.
    This stabilizes cohort size when hard filters are too restrictive.

    - Avoids address duplicates.
    - Sort key accepts 'vol24h' or 'liqUsd'; defaults to 'vol24h'.
    """
    if need_min <= 0 or len(kept) >= need_min:
        return kept

    kept_addresses: Set[str] = {row.token_address for row in kept if row.token_address}
    pool: List[Candidate] = []
    for row in universe:
        address = row.token_address
        if address and address in kept_addresses:
            continue
        if row.volume_24h_usd < min_vol_usd or row.liquidity_usd < min_liq_usd:
            continue
        p1 = row.percent_1h
        p24 = row.percent_24h
        if p1 is not None and p24 is not None and (p1 < 0.0 and p24 < 0.0):
            # clearly weak; keep pool a bit cleaner
            continue
        pool.append(row)

    key = sort_key if sort_key in _SOFT_SORT_KEYS else "vol24h"
    pool.sort(key=lambda c: _get_candidate_sort_value(c, key), reverse=True)

    for row in pool:
        if len(kept) >= need_min:
            break
        log.debug(
            "[TREND][FILTER][SOFT_FILL][KEEP] %s — vol=%.0f liq=%.0f p1=%s p24=%s",
            row.symbol,
            row.volume_24h_usd,
            row.liquidity_usd,
            row.percent_1h,
            row.percent_24h,
        )
        kept.append(row)
        if row.token_address:
            kept_addresses.add(row.token_address)

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


def preload_best_prices(candidates: List[Candidate]) -> List[TokenPrice]:
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
            candidate.symbol or "",
            candidate.chain_name or "",
            candidate.token_address or "",
            candidate.pair_address or "",
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_tokens_in_order.append(
            Token(
                symbol=candidate.symbol,
                chain=candidate.chain_name,
                tokenAddress=candidate.token_address,
                pairAddress=candidate.pair_address,
            )
        )
    if not deduped_tokens_in_order:
        return []
    return fetch_price_by_tokens_sync(deduped_tokens_in_order)


def _price_from(token_prices: List[TokenPrice], candidate: Candidate) -> Optional[float]:
    """
    Fetch a price from a list of TokenPrice objects matching the candidate's chain, symbol, token address and pair address.
    """
    for token_price in token_prices:
        if (
            token_price.token.symbol == candidate.symbol
            and token_price.token.chain == candidate.chain_name
            and token_price.token.tokenAddress == candidate.token_address
            and token_price.token.pairAddress == candidate.pair_address
        ):
            return token_price.priceUsd
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

    rows: List[NormalizedRow] = _run_awaitable_in_fresh_loop(
        fetch_trending_candidates(),
        debug_label="fetch_trending_candidates",
    )
    candidates: List[Candidate] = [_candidate_from_normalized_row(r) for r in rows]
    log.info("[TREND][FETCH] converted %d normalized rows into Candidate objects.", len(candidates))
    return candidates


def _is_address_in_open_positions(candidate_address: str, open_addresses: Set[str]) -> bool:
    """Return True if the candidate address is a currently open position."""
    return bool(candidate_address) and candidate_address in open_addresses

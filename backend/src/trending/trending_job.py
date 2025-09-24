
# src/offchain/trending_job.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from src.logger import get_logger
from src.config import settings
from src.trending.cmc_dapi import fetch_cmc_dapi_trending

# Le trader existe déjà dans ton workspace.
# On évite les dépendances rigides en appelant ses méthodes de façon "souple".
try:
    from src.execution.trader import Trader  # type: ignore
except Exception:  # pragma: no cover - tolérant si le module n'est pas encore là
    Trader = None  # type: ignore

log = get_logger(__name__)


# ------------------------ helpers & formats ------------------------

def _as_frac(x: Optional[float]) -> float:
    """
    Convertit un seuil tolérant :
      - si x > 1, on considère que c'est une valeur en points de % (ex: 2 -> 2%)
      - sinon c'est déjà une fraction (ex: 0.02 -> 2%)
    """
    if x is None:
        return 0.0
    return x / 100.0 if x > 1 else x


def _pct_or_none(v: Any) -> Optional[float]:
    return v if isinstance(v, (int, float)) else None


def _fmt_pct(x: Optional[float]) -> str:
    return f"{x*100:.2f}%" if isinstance(x, (int, float)) else "None"


def _last6(addr: str) -> str:
    return (addr[-6:] if addr else "--")


# Exclusions simples (symbole upper)
_STABLES = {
    "USDT", "USDC", "DAI", "USDS", "TUSD", "FDUSD", "PYUSD", "USDV", "USDD",
}
_MAJORS = {
    "ETH", "WETH", "WBTC", "BTC", "STETH", "WSTETH", "BNB", "MKR",
}


def _excluded(symbol: str) -> bool:
    sym = (symbol or "").upper()
    if getattr(settings, "TREND_EXCLUDE_STABLES", False) and sym in _STABLES:
        return True
    if getattr(settings, "TREND_EXCLUDE_MAJORS", False) and sym in _MAJORS:
        return True
    return False


def _passes_thresholds(
        it: Dict[str, Any],
        interval: str,
        t5: float,
        t1: float,
        t24: float,
) -> bool:
    """
    Règle de décision "strict momentum".
    - 5m : pct5m >= t5 OU pct24h >= t24 (fallback)
    - 1h : pct1h >= t1 OU pct24h >= t24 (fallback si pct1h None)
    - 4h/24h : pct24h >= t24
    """
    p5 = _pct_or_none(it.get("pct5m"))
    p1 = _pct_or_none(it.get("pct1h"))
    p24 = _pct_or_none(it.get("pct24h"))

    if interval == "5m":
        return (p5 is not None and p5 >= t5) or (p24 is not None and p24 >= t24)
    if interval == "1h":
        return (p1 is not None and p1 >= t1) or (p24 is not None and p24 >= t24)
    # 4h / 24h / autre
    return (p24 is not None and p24 >= t24)


def _softfill_ok(it: Dict[str, Any], min_vol: float, min_liq: float) -> bool:
    """
    Candidats soft-fill :
      - vol/liq OK
      - momentum non-négatif : si 1h dispo => >= 0, sinon on regarde 24h
    """
    vol = float(it.get("vol24h") or 0)
    liq = float(it.get("liqUsd") or 0)
    if vol < min_vol or liq < min_liq:
        return False

    p1 = _pct_or_none(it.get("pct1h"))
    p24 = _pct_or_none(it.get("pct24h"))
    if p1 is not None:
        return p1 >= 0
    if p24 is not None:
        return p24 >= 0
    return False


# ------------------------------ Job --------------------------------

class TrendingJob:
    def __init__(self, w3: Optional["Web3"] = None) -> None:
        """
        Accepte un client Web3 optionnel. En mode LIVE (PAPER_MODE=False), on
        tentera d'établir une connexion si non fournie (via QUICKNODE_URL).
        """
        self.source: str = settings.TREND_SOURCE
        self.interval: str = (settings.TREND_INTERVAL or "1h").lower()
        self.page_size: int = int(settings.TREND_PAGE_SIZE)
        self.max_results: int = int(settings.TREND_MAX_RESULTS)

        # Seuils (tolérants à l'unité)
        self.th5 = _as_frac(getattr(settings, "TREND_MIN_PCT_5M", 0.02))
        self.th1 = _as_frac(getattr(settings, "TREND_MIN_PCT_1H", 0.008))
        self.th24 = _as_frac(getattr(settings, "TREND_MIN_PCT_24H", 0.02))

        self.min_vol = float(getattr(settings, "TREND_MIN_VOL_USD", 100_000))
        self.min_liq = float(getattr(settings, "TREND_MIN_LIQ_USD", 50_000))

        self.softfill_min = int(getattr(settings, "TREND_SOFTFILL_MIN", 0))
        self.softfill_sort = getattr(settings, "TREND_SOFTFILL_SORT", "vol24h")

        # Trader (best effort)
        self.trader = Trader() if Trader else None

        # Etiquette pour les logs
        self.chain_tag = (getattr(settings, "TREND_CHAIN", "ethereum") or "ethereum").upper()
        self.debug_n = int(getattr(settings, "DEBUG_SAMPLE_ROWS", 6))

        # Web3 (optionnel)
        self.w3: Optional["Web3"] = w3

    # --------------- fetch ---------------

    def _fetch(self) -> List[Dict[str, Any]]:
        if self.source == "cmc_dapi":
            rows = fetch_cmc_dapi_trending(self.interval, page_size=self.page_size)
            return rows
        log.error("TREND_SOURCE '%s' inconnu", self.source)
        return []

    # --------------- onchain helpers ---------------

    def set_web3(self, w3: "Web3") -> None:
        self.w3 = w3

    def _is_connected(self, w3: "Web3") -> bool:
        try:
            return bool(w3.is_connected())  # web3>=6
        except Exception:
            try:
                return bool(w3.isConnected())  # web3<6
            except Exception:
                return False

    def _ensure_web3(self) -> bool:
        """
        S'assure qu'on dispose d'un client web3 **connecté** en LIVE.
        Si non fourni, tente QUICKNODE_URL en WS puis HTTP.
        """
        if getattr(settings, "PAPER_MODE", True):
            return False  # inutile en PAPER

        # Si déjà fourni et connecté
        if self.w3 is not None and self._is_connected(self.w3):
            return True

        # Sinon, essaie de construire depuis QUICKNODE_URL
        url = (getattr(settings, "QUICKNODE_URL", "") or os.getenv("QUICKNODE_URL", "")).strip()
        if not url:
            return False

        try:
            from web3 import Web3  # type: ignore
        except Exception:
            log.warning("web3.py non installé — onchain désactivé.")
            return False

        if url.startswith("ws"):
            try:
                w3 = Web3(Web3.WebsocketProvider(url, websocket_timeout=10))
                if self._is_connected(w3):
                    self.w3 = w3
                    return True
            except Exception:
                log.warning("WS provider KO, fallback HTTP")

        try:
            w3 = Web3(Web3.HTTPProvider(url))
            if self._is_connected(w3):
                self.w3 = w3
                return True
        except Exception as e:
            log.warning("HTTP provider KO: %s", e)

        return False

    def _onchain_scan(self) -> None:
        """
        Point d'extension pour ta logique onchain (liquidité, pools, etc.).
        Ici : simple sanity check + mise à dispo du client au Trader si possible.
        """
        if not self.w3:
            log.debug("Onchain scan sauté (w3 absent).")
            return

        # Sanity: dernier bloc, chain_id
        try:
            latest = int(self.w3.eth.block_number)  # type: ignore[attr-defined]
            try:
                chain_id = int(self.w3.eth.chain_id)  # type: ignore[attr-defined]
            except Exception:
                chain_id = -1
            log.info("[Onchain] OK — latest block=%s chain_id=%s", latest, chain_id)
        except Exception as e:
            log.warning("[Onchain] Impossible de lire le dernier bloc : %s", e)

        # Donner w3 au Trader si celui-ci expose un setter / attribut
        if self.trader is not None:
            try:
                if hasattr(self.trader, "set_web3") and callable(getattr(self.trader, "set_web3")):
                    self.trader.set_web3(self.w3)  # type: ignore[arg-type]
                elif hasattr(self.trader, "w3"):
                    setattr(self.trader, "w3", self.w3)
            except Exception as e:
                log.debug("Trader web3 injection skipped: %s", e)

    # --------------- core ---------------

    def run_once(self) -> None:
        if not getattr(settings, "TREND_ENABLE", True):
            log.info("Trending disabled (TREND_ENABLE=false)")
            return

        # LIVE => s'assurer du client web3
        if not getattr(settings, "PAPER_MODE", True):
            self._ensure_web3()

        rows = self._fetch()
        if not rows:
            log.warning("Trending %s: 0 rows", self.source)
            return

        # Aperçu des premières lignes
        for i, it in enumerate(rows[: self.debug_n], 1):
            log.debug(
                "[RAW PREVIEW] #%d %s Δ1h=%s Δ24h=%s vol=$%.0f liq=$%.0f 0x…%s",
                i,
                it.get("symbol"),
                _fmt_pct(it.get("pct1h")),
                _fmt_pct(it.get("pct24h")),
                float(it.get("vol24h") or 0),
                float(it.get("liqUsd") or 0),
                _last6(it.get("address") or ""),
            )

        kept: List[Dict[str, Any]] = []
        rejects_lowvol = rejects_lowliq = rejects_lowpct = rejects_excl = 0

        # -------- filtre strict --------
        for it in rows:
            sym = (it.get("symbol") or "").upper()
            addr = it.get("address") or ""
            vol = float(it.get("vol24h") or 0)
            liq = float(it.get("liqUsd") or 0)

            # Exclusions symboliques
            if _excluded(sym):
                rejects_excl += 1
                continue

            # Seuils vol/liquidity
            if vol < self.min_vol:
                rejects_lowvol += 1
                continue
            if liq < self.min_liq:
                rejects_lowliq += 1
                continue

            # Momentum
            if not _passes_thresholds(it, self.interval, self.th5, self.th1, self.th24):
                rejects_lowpct += 1
                log.debug(
                    "[REJECT PCT] %s Δ1h=%s Δ24h=%s (need Δ1h≥%.2f%% or Δ24h≥%.2f%%) (0x…%s)",
                    sym,
                    _fmt_pct(it.get("pct1h")),
                    _fmt_pct(it.get("pct24h")),
                    self.th1 * 100,
                    self.th24 * 100,
                    _last6(addr),
                    )
                continue

            kept.append(it)
            if len(kept) >= self.max_results:
                break

        strict_kept = len(kept)

        # -------- soft-fill au besoin --------
        soft_added: List[Dict[str, Any]] = []
        need = max(0, self.softfill_min - strict_kept)
        if need > 0:
            pool = [
                r for r in rows
                if (r not in kept)
                   and _softfill_ok(r, self.min_vol, self.min_liq)
                   and not _excluded((r.get("symbol") or "").upper())
            ]
            key = self.softfill_sort if self.softfill_sort in {"vol24h", "liqUsd"} else "vol24h"
            pool.sort(key=lambda x: float(x.get(key) or 0.0), reverse=True)

            for r in pool:
                if len(kept) >= self.max_results or len(soft_added) >= need:
                    break
                kept.append(r)
                soft_added.append(r)

            if soft_added:
                log.info(
                    "Soft-fill %d assets by %s (strict kept=%d)",
                    len(soft_added), key, strict_kept
                )

        # -------- récap --------
        log.info(
            "Trending %s kept=%d/%d (interval=%s, vol≥$%.0f liq≥$%.0f) — rejects: lowvol=%d lowliq=%d lowpct=%d excl=%d",
            self.chain_tag,
            len(kept),
            strict_kept,
            self.interval,
            self.min_vol,
            self.min_liq,
            rejects_lowvol,
            rejects_lowliq,
            rejects_lowpct,
            rejects_excl,
        )

        # -------- onchain (LIVE seulement) --------
        if not getattr(settings, "PAPER_MODE", True):
            self._onchain_scan()

        # -------- passage au trader --------
        if not kept:
            return

        if self.trader is None:
            log.warning("Trader indisponible (module non importé). Pas d'exécution.")
            return

        # On tente d'abord des méthodes "batch", puis on itère si absent.
        batch_methods = ("on_trending", "scan", "process_candidates", "process", "consider_batch")
        called = False
        for m in batch_methods:
            fn = getattr(self.trader, m, None)
            if callable(fn):
                try:
                    fn(kept)
                    called = True
                    break
                except Exception as e:
                    log.exception("Trader.%s error: %s", m, e)

        if not called:
            per_item_methods = ("maybe_buy", "try_enter", "on_signal", "consider", "trade", "buy")
            for it in kept:
                for m in per_item_methods:
                    fn = getattr(self.trader, m, None)
                    if callable(fn):
                        try:
                            fn(it)
                            break
                        except Exception as e:
                            log.exception("Trader.%s error on %s: %s", m, it.get("symbol"), e)
                            break
            if not any(getattr(self.trader, m, None) for m in per_item_methods):
                log.warning(
                    "Aucune méthode compatible trouvée sur Trader. "
                    "Ajoute par ex. Trader.on_trending(candidates) ou Trader.maybe_buy(item)."
                )

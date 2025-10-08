from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, cast, List

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    ViewportSize,
)

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ChartCaptureResult:
    """Container for a captured chart image."""
    png_bytes: bytes
    source_name: str
    timeframe_minutes: int
    lookback_minutes: int
    file_path: str | None = None


class ChartCaptureError(Exception):
    """Raised when the chart could not be captured."""


class ChartCaptureService:
    """
    Renders a DexScreener page in a headless browser and returns a full-page PNG screenshot.

    Key features:
    - Adaptive TradingView interval based on token age (minutes) if provided.
    - Interval application via the TradingView toolbar within the iframe (fallback to keyboard).
    - Full-page screenshots to include DexScreener metrics in addition to the candles.
    - Short-lived caching keyed by pair and chosen interval.
    - Optional on-disk persistence for auditability.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, tuple[float, bytes, str, str | None]] = {}

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        """Convert any identifier (symbol, chain:address) into a filesystem-safe string."""
        value = (value or "").strip().lower()
        value = value.replace(":", "_").replace("/", "_")
        return re.sub(r"[^a-z0-9._-]+", "-", value) or "unknown"

    def _persist_png(
            self,
            png_bytes: bytes,
            *,
            identifier: str,
            source: str,
            timeframe_minutes: int,
            lookback_minutes: int,
            interval_label: Optional[str] = None,
    ) -> str:
        """
        Save the PNG bytes to disk under SCREENSHOT_DIR with a descriptive filename.
        Returns the file path (string).
        """
        screenshots_dir = Path(settings.SCREENSHOT_DIR)
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        interval_part = f"_iv{interval_label}" if interval_label else ""
        file_name = (
            f"{timestamp}_{source}_{identifier}{interval_part}_"
            f"tf{timeframe_minutes}_lb{lookback_minutes}.png"
        )
        file_path = screenshots_dir / file_name
        file_path.write_bytes(png_bytes)

        log.info("ChartCapture: screenshot saved to %s", str(file_path))
        return str(file_path)

    def _build_dexscreener_url(
            self,
            chain_name: str,
            pair_address: str,
            interval: Optional[str] = None,
    ) -> str:
        """
        Build the DexScreener pair URL. When provided, append `interval` as a query parameter.
        DexScreener may ignore it; we also try to set it inside the iframe via UI controls.
        """
        url = f"https://dexscreener.com/{chain_name}/{pair_address}?embed=1"
        if interval:
            url += f"&interval={interval}"
        return url

    @staticmethod
    def _map_interval_to_toolbar_values(interval: str) -> List[str]:
        """
        Map an interval string to TradingView toolbar values.
        Examples:
          "1" -> ["1"], "3" -> ["3"], "5" -> ["5"], "15" -> ["15"], "30" -> ["30"],
          "60" -> ["60"], "240" -> ["240"], "D" -> ["1D", "D"], "W" -> ["1W", "W"]
        """
        iv = (interval or "").strip().upper()
        if iv == "D":
            return ["1D", "D"]
        if iv == "W":
            return ["1W", "W"]
        return [iv]

    def _try_set_tradingview_interval_via_toolbar(self, page, interval: str) -> bool:
        """
        Set the TradingView interval by clicking the toolbar radio button inside the iframe.
        We avoid page.wait_for_function on cross-frame elements and instead poll the
        button's aria-checked attribute (reliable with Playwright Locators).
        """
        try:
            page.wait_for_selector("iframe", state="attached")
            frame = page.frame_locator("iframe").first

            toolbar = frame.locator("#header-toolbar-intervals")
            toolbar.wait_for(state="visible", timeout=int(settings.CHART_CAPTURE_WAIT_CANVAS_MS))

            candidates = self._map_interval_to_toolbar_values(interval)
            for value in candidates:
                button = toolbar.locator(f"button[role='radio'][data-value='{value}']").first
                if button.count() == 0:
                    continue

                try:
                    aria_checked = (button.get_attribute("aria-checked") or "").lower()
                    if aria_checked == "true":
                        log.debug("ChartCapture: toolbar already at interval=%s", value)
                        return True
                except Exception:
                    pass

                button.click()
                deadline = time.time() + 2.5
                while time.time() < deadline:
                    try:
                        if (button.get_attribute("aria-checked") or "").lower() == "true":
                            page.wait_for_timeout(300)
                            log.debug("ChartCapture: toolbar interval set to %s", value)
                            return True
                    except Exception:
                        button = toolbar.locator(f"button[role='radio'][data-value='{value}']").first
                    page.wait_for_timeout(80)

                active = toolbar.locator("button[role='radio'][aria-checked='true']").first
                if active.count() > 0:
                    try:
                        if (active.get_attribute("data-value") or "").upper() == value.upper():
                            page.wait_for_timeout(300)
                            log.debug("ChartCapture: toolbar interval confirmed via active radio = %s", value)
                            return True
                    except Exception:
                        pass

                log.debug("ChartCapture: toolbar click did not confirm for %s; trying next candidate", value)

            log.debug("ChartCapture: no matching interval button found in toolbar for '%s'", interval)
            return False

        except Exception as exc:
            log.debug("ChartCapture: toolbar operation failed (%s)", exc)
            return False

    def _try_set_tradingview_interval_via_keyboard(self, page, interval: str) -> bool:
        """
        Fallback method: focus the canvas and type the interval (digits + Enter), or hotkey (D/W).
        Returns True if a key sequence was sent (not a guarantee the interval is applied).
        """
        try:
            frame = page.frame_locator("iframe").first
            canvas = frame.locator("canvas").first
            canvas.wait_for(state="visible", timeout=int(settings.CHART_CAPTURE_WAIT_CANVAS_MS))
            canvas.click()

            iv = (interval or "").strip().upper()
            if iv == "D":
                frame.press("body", "KeyD")
            elif iv == "W":
                frame.press("body", "KeyW")
            else:
                for ch in iv:
                    if ch.isdigit():
                        frame.press("body", f"Digit{ch}")
                frame.press("body", "Enter")

            page.wait_for_timeout(350)
            log.debug("ChartCapture: keyboard interval sequence sent for %s", interval)
            return True
        except Exception as exc:
            log.debug("ChartCapture: keyboard interval failed (%s)", exc)
            return False

    @staticmethod
    def _select_interval_from_age_hours(age_hours: float) -> str:
        """
        Select a TradingView interval that makes the history reasonably visible for the given token age.

        Heuristic mapping (can be tuned later):
          <= 90 min    -> "1"
          <= 6h        -> "3"
          <= 24h       -> "5"
          <= 3d        -> "15"
          <= 10d       -> "60"     (1h)
          <= 30d       -> "240"    (4h)
          <= 6 months  -> "D"      (1 day)
          > 6 months   -> "W"      (1 week)
        """
        m = float(max(1.0, age_hours)) * 60
        if m <= 90:
            return "1"
        if m <= 6 * 60:
            return "3"
        if m <= 24 * 60:
            return "5"
        if m <= 3 * 24 * 60:
            return "15"
        if m <= 10 * 24 * 60:
            return "60"
        if m <= 30 * 24 * 60:
            return "240"
        if m <= 180 * 24 * 60:
            return "D"
        return "W"

    def _screenshot_dexscreener_fullpage(
            self,
            target_url: str,
            interval: Optional[str],
            timeout_sec: int,
    ) -> bytes:
        """
        Open DexScreener, wait for TradingView iframe, optionally apply interval,
        and capture a full-page PNG.
        """
        log.debug("ChartCapture: opening %s", target_url)
        with sync_playwright() as p:
            engine = (settings.CHART_CAPTURE_BROWSER or "chromium").lower()
            if engine == "firefox":
                browser = p.firefox.launch(headless=bool(settings.CHART_CAPTURE_HEADLESS))
            elif engine == "webkit":
                browser = p.webkit.launch(headless=bool(settings.CHART_CAPTURE_HEADLESS))
            else:
                browser = p.chromium.launch(
                    headless=bool(settings.CHART_CAPTURE_HEADLESS),
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )

            context = None
            try:
                context = browser.new_context(
                    viewport=cast(
                        ViewportSize,
                        {
                            "width": int(settings.CHART_CAPTURE_VIEWPORT_WIDTH),
                            "height": int(settings.CHART_CAPTURE_VIEWPORT_HEIGHT),
                        },
                    ),
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                page = context.new_page()
                page.set_default_timeout(timeout_sec * 1000)

                page.goto(target_url, wait_until="domcontentloaded")
                page.wait_for_selector("iframe", state="attached")

                if interval:
                    applied = self._try_set_tradingview_interval_via_toolbar(page, interval)
                    if not applied:
                        self._try_set_tradingview_interval_via_keyboard(page, interval)

                frame_loc = page.frame_locator("iframe").first
                try:
                    frame_loc.locator("canvas").first.wait_for(
                        state="visible",
                        timeout=int(settings.CHART_CAPTURE_WAIT_CANVAS_MS),
                    )
                except PlaywrightTimeoutError:
                    log.warning(
                        "ChartCapture: canvas not visible within %d ms (continuing anyway)",
                        int(settings.CHART_CAPTURE_WAIT_CANVAS_MS),
                    )

                page.wait_for_timeout(int(settings.CHART_CAPTURE_AFTER_RENDER_MS))
                png_bytes = page.screenshot(type="png", full_page=True)
                return png_bytes

            except PlaywrightTimeoutError as exc:
                raise ChartCaptureError(f"Timeout while loading {target_url}") from exc
            finally:
                try:
                    if context is not None:
                        context.close()
                finally:
                    browser.close()

    def capture_chart_png(
            self,
            *,
            symbol: Optional[str],
            chain_name: Optional[str],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
            token_age_hours: float,
    ) -> ChartCaptureResult:
        """
        DexScreener-only capture with adaptive TradingView interval.

        Parameters
        ----------
        symbol : Optional[str]
            Unused for on-chain pairs; kept for signature compatibility.
        chain_name : Optional[str]
            The on-chain network name (e.g., 'solana', 'ethereum', 'bsc', 'base', 'abstract').
        pair_address : Optional[str]
            The DEX pair address.
        timeframe_minutes : int
            Poseidon's configured timeframe (kept for file naming and compatibility).
        lookback_minutes : int
            Poseidon's configured lookback (kept for file naming and compatibility).
        token_age_hours : Optional[float]
            If provided, selects an appropriate TradingView interval to fit history.

        Returns
        -------
        ChartCaptureResult
            The full-page PNG bytes and metadata.

        Notes
        -----
        - A small cache prevents hammering the same pair + interval repeatedly.
        - The chosen interval is logged and appended to the saved filename when persistence is enabled.
        """
        if not (chain_name and pair_address):
            raise ChartCaptureError("Insufficient data to capture chart (need chain and address)")

        if token_age_hours is not None:
            preferred_interval = self._select_interval_from_age_hours(float(token_age_hours))
            log.debug("ChartCapture: token_age=%.2f hours -> interval=%s", float(token_age_hours), preferred_interval)
        else:
            preferred_interval = "D" if int(timeframe_minutes) >= 60 * 24 else str(int(timeframe_minutes))
            log.debug("ChartCapture: using fallback interval from timeframe -> interval=%s", preferred_interval)

        cache_key = f"{chain_name}:{pair_address}:{preferred_interval}:{timeframe_minutes}:{lookback_minutes}"
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < settings.CHART_AI_MIN_CACHE_SECONDS:
            log.debug("ChartCapture: returning cached image for %s", cache_key)
            return ChartCaptureResult(
                png_bytes=cached[1],
                source_name=cached[2],
                timeframe_minutes=timeframe_minutes,
                lookback_minutes=lookback_minutes,
                file_path=cached[3],
            )

        timeout_sec = int(settings.CHART_CAPTURE_TIMEOUT_SEC)
        persisted_path: str | None = None

        identifier_raw = f"{chain_name}:{pair_address}"
        identifier = self._sanitize_identifier(identifier_raw)

        url = self._build_dexscreener_url(chain_name, pair_address, interval=preferred_interval)
        try:
            png = self._screenshot_dexscreener_fullpage(
                target_url=url,
                interval=preferred_interval,
                timeout_sec=timeout_sec,
            )
            if settings.CHART_AI_SAVE_SCREENSHOTS:
                persisted_path = self._persist_png(
                    png,
                    identifier=identifier,
                    source="dexscreener",
                    timeframe_minutes=timeframe_minutes,
                    lookback_minutes=lookback_minutes,
                    interval_label=preferred_interval,
                )
            self._cache[cache_key] = (now, png, "dexscreener", persisted_path)
            log.info(
                "ChartCapture: captured DexScreener page for %s/%s (interval=%s, tf=%dm, full_page)",
                chain_name,
                pair_address,
                preferred_interval,
                timeframe_minutes,
            )
            return ChartCaptureResult(
                png_bytes=png,
                source_name="dexscreener",
                timeframe_minutes=timeframe_minutes,
                lookback_minutes=lookback_minutes,
                file_path=persisted_path,
            )
        except Exception as exc:
            log.warning("ChartCapture: DexScreener failed for %s/%s: %s", chain_name, pair_address, exc)
            raise ChartCaptureError(f"Dexscreener capture failed for {chain_name}/{pair_address}") from exc

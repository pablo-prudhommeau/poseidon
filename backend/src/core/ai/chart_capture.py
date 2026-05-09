from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional, cast

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    ViewportSize,
    Page,
)

from src.configuration.config import settings
from src.core.ai.chart_structures import ChartCaptureResult, ChartCacheEntry
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class ChartCaptureError(Exception):
    pass


class ChartCaptureService:
    def __init__(self) -> None:
        self._screenshots_cache: dict[str, ChartCacheEntry] = {}

    @staticmethod
    def _sanitize_string_identifier(raw_identifier: str) -> str:
        sanitized_identifier = (raw_identifier or "").strip().lower()
        sanitized_identifier = sanitized_identifier.replace(":", "_").replace("/", "_")
        return re.sub(r"[^a-z0-9._-]+", "-", sanitized_identifier) or "unknown"

    def _persist_screenshot_to_disk(
            self,
            screenshot_bytes: bytes,
            *,
            sanitized_identifier: str,
            source_name: str,
            timeframe_minutes: int,
            lookback_minutes: int,
            interval_label: Optional[str] = None,
    ) -> str:
        screenshots_directory = Path(settings.SCREENSHOT_DIR)
        screenshots_directory.mkdir(parents=True, exist_ok=True)

        current_timestamp = get_current_local_datetime().strftime("%Y%m%d-%H%M%S")
        interval_suffix = f"_iv{interval_label}" if interval_label else ""
        file_name = (
            f"{current_timestamp}_{source_name}_{sanitized_identifier}{interval_suffix}_"
            f"tf{timeframe_minutes}_lb{lookback_minutes}.png"
        )
        destination_file_path = screenshots_directory / file_name
        destination_file_path.write_bytes(screenshot_bytes)

        logger.info("[AI][CHART][CAPTURE][PERSIST] Screenshot successfully saved to disk at %s", str(destination_file_path))
        return str(destination_file_path)

    def _build_dexscreener_target_url(
            self,
            chain: BlockchainNetwork,
            pair_address: str,
            time_interval: Optional[str] = None,
    ) -> str:
        target_url = f"https://dexscreener.com/{chain.value}/{pair_address}?embed=1"
        if time_interval:
            target_url += f"&interval={time_interval}"
        return target_url

    @staticmethod
    def _map_time_interval_to_toolbar_values(time_interval: str) -> list[str]:
        normalized_interval = (time_interval or "").strip().upper()
        if normalized_interval == "D":
            return ["1D", "D"]
        if normalized_interval == "W":
            return ["1W", "W"]
        return [normalized_interval]

    def _try_set_tradingview_interval_via_toolbar(self, browser_page: Page, time_interval: str) -> bool:
        try:
            browser_page.wait_for_selector("iframe", state="attached")
            tradingview_iframe = browser_page.frame_locator("iframe").first

            intervals_toolbar = tradingview_iframe.locator("#header-toolbar-intervals")
            intervals_toolbar.wait_for(state="visible", timeout=int(settings.CHART_CAPTURE_WAIT_CANVAS_MS))

            toolbar_value_candidates = self._map_time_interval_to_toolbar_values(time_interval)
            for candidate_value in toolbar_value_candidates:
                interval_button = intervals_toolbar.locator(f"button[role='radio'][data-value='{candidate_value}']").first
                if interval_button.count() == 0:
                    continue

                try:
                    is_button_aria_checked = (interval_button.get_attribute("aria-checked") or "").lower()
                    if is_button_aria_checked == "true":
                        logger.debug("[AI][CHART][CAPTURE][TOOLBAR] Toolbar is already set at interval %s", candidate_value)
                        return True
                except Exception:
                    pass

                interval_button.click()
                timeout_deadline = time.time() + 2.5
                while time.time() < timeout_deadline:
                    try:
                        if (interval_button.get_attribute("aria-checked") or "").lower() == "true":
                            browser_page.wait_for_timeout(300)
                            logger.debug("[AI][CHART][CAPTURE][TOOLBAR] Toolbar interval successfully set to %s", candidate_value)
                            return True
                    except Exception:
                        interval_button = intervals_toolbar.locator(f"button[role='radio'][data-value='{candidate_value}']").first
                    browser_page.wait_for_timeout(80)

                active_interval_button = intervals_toolbar.locator("button[role='radio'][aria-checked='true']").first
                if active_interval_button.count() > 0:
                    try:
                        if (active_interval_button.get_attribute("data-value") or "").upper() == candidate_value.upper():
                            browser_page.wait_for_timeout(300)
                            logger.debug("[AI][CHART][CAPTURE][TOOLBAR] Toolbar interval confirmed via active radio button to %s", candidate_value)
                            return True
                    except Exception:
                        pass

                logger.debug("[AI][CHART][CAPTURE][TOOLBAR] Toolbar click verification failed for candidate %s, trying next fallback option", candidate_value)

            logger.debug("[AI][CHART][CAPTURE][TOOLBAR] No matching interval button found in toolbar for %s", time_interval)
            return False

        except Exception as exception:
            logger.exception("[AI][CHART][CAPTURE][TOOLBAR] Toolbar interval setting operation failed", exception)
            return False

    def _try_set_tradingview_interval_via_keyboard(self, browser_page: Page, time_interval: str) -> bool:
        try:
            tradingview_iframe = browser_page.frame_locator("iframe").first
            chart_canvas = tradingview_iframe.locator("canvas").first
            chart_canvas.wait_for(state="visible", timeout=int(settings.CHART_CAPTURE_WAIT_CANVAS_MS))
            chart_canvas.click()

            normalized_interval = (time_interval or "").strip().upper()
            if normalized_interval == "D":
                tradingview_iframe.press("body", "KeyD")
            elif normalized_interval == "W":
                tradingview_iframe.press("body", "KeyW")
            else:
                for character in normalized_interval:
                    if character.isdigit():
                        tradingview_iframe.press("body", f"Digit{character}")
                tradingview_iframe.press("body", "Enter")

            browser_page.wait_for_timeout(350)
            logger.debug("[AI][CHART][CAPTURE][KEYBOARD] Keyboard interval sequence successfully dispatched for interval %s", time_interval)
            return True
        except Exception as exception:
            logger.exception("[AI][CHART][CAPTURE][KEYBOARD] Keyboard interval setting operation failed", exception)
            return False

    @staticmethod
    def _select_optimal_interval_from_token_age_hours(token_age_in_hours: float) -> str:
        token_age_in_minutes = max(1.0, token_age_in_hours) * 60.0
        if token_age_in_minutes <= 90.0:
            return "1"
        if token_age_in_minutes <= 360.0:
            return "3"
        if token_age_in_minutes <= 1440.0:
            return "5"
        if token_age_in_minutes <= 4320.0:
            return "15"
        if token_age_in_minutes <= 14400.0:
            return "60"
        if token_age_in_minutes <= 43200.0:
            return "240"
        if token_age_in_minutes <= 259200.0:
            return "D"
        return "W"

    def _screenshot_dexscreener_fullpage_render(
            self,
            target_url: str,
            time_interval: Optional[str],
            timeout_in_seconds: int,
    ) -> bytes:
        logger.debug("[AI][CHART][CAPTURE][BROWSER] Initiating headless browser navigation to %s", target_url)

        with sync_playwright() as playwright_context_manager:
            browser_engine_choice = (settings.CHART_CAPTURE_BROWSER or "chromium").lower()

            if browser_engine_choice == "firefox":
                headless_browser = playwright_context_manager.firefox.launch(headless=bool(settings.CHART_CAPTURE_HEADLESS))
            elif browser_engine_choice == "webkit":
                headless_browser = playwright_context_manager.webkit.launch(headless=bool(settings.CHART_CAPTURE_HEADLESS))
            else:
                headless_browser = playwright_context_manager.chromium.launch(
                    headless=bool(settings.CHART_CAPTURE_HEADLESS),
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )

            browser_context = None
            try:
                browser_context = headless_browser.new_context(
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
                browser_page = browser_context.new_page()
                browser_page.set_default_timeout(timeout_in_seconds * 1000)

                browser_page.goto(target_url, wait_until="domcontentloaded")
                browser_page.wait_for_selector("iframe", state="attached")

                if time_interval:
                    is_interval_applied = self._try_set_tradingview_interval_via_toolbar(browser_page, time_interval)
                    if not is_interval_applied:
                        self._try_set_tradingview_interval_via_keyboard(browser_page, time_interval)

                tradingview_iframe_locator = browser_page.frame_locator("iframe").first
                try:
                    tradingview_iframe_locator.locator("canvas").first.wait_for(
                        state="visible",
                        timeout=int(settings.CHART_CAPTURE_WAIT_CANVAS_MS),
                    )
                except PlaywrightTimeoutError as exception:
                    logger.warning(
                        "[AI][CHART][CAPTURE][BROWSER] Chart canvas failed to become visible within the allocated timeout of %s milliseconds, proceeding with capture fallback",
                        int(settings.CHART_CAPTURE_WAIT_CANVAS_MS),
                        exception
                    )

                browser_page.wait_for_timeout(int(settings.CHART_CAPTURE_AFTER_RENDER_MS))
                captured_png_bytes = browser_page.screenshot(type="png", full_page=True)
                return captured_png_bytes

            except PlaywrightTimeoutError as exception:
                logger.exception("[AI][CHART][CAPTURE][BROWSER] Critical timeout encountered while loading target URL %s", target_url, exception)
                raise ChartCaptureError(f"Timeout while loading {target_url}") from exception
            finally:
                try:
                    if browser_context is not None:
                        browser_context.close()
                finally:
                    headless_browser.close()

    def capture_chart_png(
            self,
            *,
            symbol: Optional[str],
            chain: Optional[BlockchainNetwork],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
            token_age_hours: Optional[float] = None,
    ) -> ChartCaptureResult:
        if not chain or not pair_address:
            raise ChartCaptureError("Insufficient data provided to capture chart: chain name and pair address are strictly required")

        if token_age_hours is not None:
            preferred_time_interval = self._select_optimal_interval_from_token_age_hours(token_age_hours)
            logger.debug("[AI][CHART][CAPTURE][INTERVAL] Token age of %s hours evaluated, selecting optimal time interval %s", token_age_hours, preferred_time_interval)
        else:
            preferred_time_interval = "D" if timeframe_minutes >= 1440 else str(timeframe_minutes)
            logger.debug("[AI][CHART][CAPTURE][INTERVAL] Using fallback time interval derived from timeframe, selecting interval %s", preferred_time_interval)

        chart_cache_key = f"{chain.value}:{pair_address}:{preferred_time_interval}:{timeframe_minutes}:{lookback_minutes}"
        current_timestamp = time.time()
        cached_capture_entry = self._screenshots_cache.get(chart_cache_key)

        if cached_capture_entry and (current_timestamp - cached_capture_entry.timestamp) < settings.CHART_AI_MIN_CACHE_SECONDS:
            logger.info("[AI][CHART][CAPTURE][CACHE] Returning cached chart image hit for cache key %s", chart_cache_key)
            return ChartCaptureResult(
                png_bytes=cached_capture_entry.png_bytes,
                source_name=cached_capture_entry.source_name,
                timeframe_minutes=timeframe_minutes,
                lookback_minutes=lookback_minutes,
                file_path=cached_capture_entry.file_path,
            )

        capture_timeout_in_seconds = int(settings.CHART_CAPTURE_TIMEOUT_SEC)
        persisted_file_path: Optional[str] = None

        raw_token_identifier = f"{chain.value}:{pair_address}"
        sanitized_token_identifier = self._sanitize_string_identifier(raw_token_identifier)

        dexscreener_target_url = self._build_dexscreener_target_url(chain, pair_address, time_interval=preferred_time_interval)

        try:
            captured_png_payload = self._screenshot_dexscreener_fullpage_render(
                target_url=dexscreener_target_url,
                time_interval=preferred_time_interval,
                timeout_in_seconds=capture_timeout_in_seconds,
            )

            if settings.CHART_AI_SAVE_SCREENSHOTS:
                persisted_file_path = self._persist_screenshot_to_disk(
                    captured_png_payload,
                    sanitized_identifier=sanitized_token_identifier,
                    source_name="dexscreener",
                    timeframe_minutes=timeframe_minutes,
                    lookback_minutes=lookback_minutes,
                    interval_label=preferred_time_interval,
                )

            self._screenshots_cache[chart_cache_key] = ChartCacheEntry(
                timestamp=current_timestamp,
                png_bytes=captured_png_payload,
                source_name="dexscreener",
                file_path=persisted_file_path
            )

            logger.info(
                "[AI][CHART][CAPTURE][SUCCESS] DexScreener chart page successfully captured for token %s on chain %s with interval %s and timeframe %s minutes",
                pair_address,
                chain.value,
                preferred_time_interval,
                timeframe_minutes,
            )

            return ChartCaptureResult(
                png_bytes=captured_png_payload,
                source_name="dexscreener",
                timeframe_minutes=timeframe_minutes,
                lookback_minutes=lookback_minutes,
                file_path=persisted_file_path,
            )
        except Exception as exception:
            logger.exception("[AI][CHART][CAPTURE][FAILURE] DexScreener chart capture completely failed for token %s on chain %s", pair_address, chain.value, exception)
            raise ChartCaptureError(f"Dexscreener capture failed for {chain.value}/{pair_address}") from exception

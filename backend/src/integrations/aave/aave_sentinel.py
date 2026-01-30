from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any, Dict, List, Tuple

import httpx
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract
from web3.types import TxParams

from src.configuration.config import settings
from src.core.utils.format_utils import format_currency, format_percent
from src.integrations.aave.aave_abis import (
    AAVE_POOL_ABI,
    ADDRESS_PROVIDER_ABI,
    AAVE_ORACLE_ABI,
    ERC20_ABI,
    RAY_UNITS,
    SECONDS_PER_YEAR
)
from src.integrations.aave.aave_models import AaveAssetDetails, AavePositionSnapshot, SentinelState
from src.logging.logger import get_logger

logger = get_logger(__name__)

Account.enable_unaudited_hdwallet_features()

STABLECOIN_SYMBOLS = {"USDC", "USDC.e", "USDT", "USDt", "DAI", "FRAX", "MIM", "BUSD"}


class AaveSentinelService:
    """
    Autonomous service monitoring Aave V3 health factor and position metrics.
    Ensures liquidity safety, reports financial performance, and prevents notification fatigue.
    It also listens for Telegram commands (e.g., /snapshot) to provide on-demand reports.
    """

    def __init__(self) -> None:
        self.is_running: bool = False
        self._web3_client: Optional[AsyncWeb3] = None
        self._pool_contract: Optional[AsyncContract] = None
        self._usdc_contract: Optional[AsyncContract] = None
        self._oracle_contract: Optional[AsyncContract] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(settings.AAVE_MAX_CONCURRENT_ASSET_SCANS)
        self._wallet_address: str = ""
        self._private_key: str = ""
        self._state: SentinelState = SentinelState()
        self._last_telegram_update_id: int = 0
        self._initial_basis_usd: Optional[float] = settings.AAVE_INITIAL_DEPOSIT_USD

    def _derive_credentials(self) -> None:
        """Derives wallet credentials from the configured mnemonic."""
        if not settings.AAVE_MNEMONIC:
            logger.warning("[AAVE][SENTINEL] Configuration missing: AAVE_MNEMONIC not set. Operation restricted.")
            return

        try:
            account: LocalAccount = Account.from_mnemonic(
                settings.AAVE_MNEMONIC,
                account_path=f"m/44'/60'/0'/0/{settings.AAVE_DERIVATION_INDEX}"
            )
            self._private_key = account.key.hex()
            self._wallet_address = account.address
            logger.info(f"[AAVE][SENTINEL] Wallet loaded successfully: {self._wallet_address}")

        except Exception as error:
            logger.error(f"[AAVE][SENTINEL] Credential derivation failed: {error}")

    async def _initialize_resources(self) -> None:
        """Lazy initialization of Web3, Oracle, and HTTP clients."""
        if not self._private_key:
            self._derive_credentials()

        if not self._web3_client:
            rpc_url = settings.AVALANCHE_RPC_URL
            self._web3_client = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

            pool_address_checksum = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
            self._pool_contract = self._web3_client.eth.contract(address=pool_address_checksum, abi=AAVE_POOL_ABI)

            usdc_address_checksum = AsyncWeb3.to_checksum_address(settings.AAVE_USDC_ADDRESS)
            self._usdc_contract = self._web3_client.eth.contract(address=usdc_address_checksum, abi=ERC20_ABI)

            try:
                provider_address = await self._pool_contract.functions.ADDRESSES_PROVIDER().call()
                provider_contract = self._web3_client.eth.contract(address=provider_address, abi=ADDRESS_PROVIDER_ABI)
                oracle_address = await provider_contract.functions.getPriceOracle().call()
                self._oracle_contract = self._web3_client.eth.contract(address=oracle_address, abi=AAVE_ORACLE_ABI)
                logger.debug(f"[AAVE][SENTINEL] Oracle found at: {oracle_address}")
            except Exception as error:
                logger.error(f"[AAVE][SENTINEL] Failed to init Oracle: {error}")

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=10.0)

    async def _send_telegram_alert(self, title: str, message: str, level: str = "INFO") -> None:
        """Sends a formatted notification via the Telegram integration."""
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return

        emoji_map = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "DANGER": "🚨",
            "SUCCESS": "✅",
            "CRITICAL": "💀"
        }

        timestamp = datetime.now().strftime("%H:%M:%S")
        full_title = f"{emoji_map.get(level, 'ℹ️')} {title} ({timestamp})"

        api_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        text_body = f"*{full_title}*\n\n{message}"

        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text_body,
            "parse_mode": "Markdown"
        }

        try:
            if self._http_client:
                await self._http_client.post(api_url, json=payload)
        except Exception as error:
            logger.error(f"[AAVE][SENTINEL] Telegram alert failed: {error}")

    async def _register_bot_commands(self) -> None:
        """Registers the list of available commands with the Telegram Bot API."""
        if not settings.TELEGRAM_BOT_TOKEN:
            return

        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setMyCommands"

        commands = [
            {"command": "snapshot", "description": "📸 Afficher le statut du portefeuille"},
        ]

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            response = await self._http_client.post(url, json={"commands": commands})

            if response.status_code == 200 and response.json().get("ok"):
                logger.info("[AAVE][SENTINEL] Telegram commands registered successfully.")
            else:
                logger.warning(f"[AAVE][SENTINEL] Failed to register Telegram commands: {response.text}")

        except Exception as error:
            logger.warning(f"[AAVE][SENTINEL] Error registering Telegram commands: {error}")

    async def _process_telegram_commands(self) -> None:
        """Polls Telegram for new commands (specifically /snapshot)."""
        if not settings.TELEGRAM_BOT_TOKEN:
            return

        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"

        payload: Dict[str, Any] = {
            "offset": self._last_telegram_update_id + 1,
            "allowed_updates": ["message"],
            "timeout": 0
        }

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            response = await self._http_client.post(url, json=payload)

            if response.status_code != 200:
                return

            data = response.json()
            if not data.get("ok"):
                return

            results = data.get("result", [])
            for update in results:
                update_id = update.get("update_id")
                self._last_telegram_update_id = update_id

                message = update.get("message", {})
                text = message.get("text", "").strip()

                if text == "/snapshot":
                    logger.info("[AAVE][SENTINEL] Manual snapshot requested via Telegram.")
                    await self._send_telegram_alert("Snapshot Demandé", "📸 Calcul du snapshot en cours...", "INFO")

                    snapshot = await self._fetch_position_snapshot()
                    if snapshot:
                        formatted_message = await self._format_notification_message(snapshot)
                        await self._send_telegram_alert("Snapshot Manuel", formatted_message, "INFO")
                    else:
                        await self._send_telegram_alert("Erreur", "Impossible de récupérer les données Aave.", "WARNING")

        except Exception as error:
            logger.debug(f"[AAVE][SENTINEL] Telegram polling error: {error}")

    async def _fetch_usd_eur_rate(self) -> float:
        """Fetches the real-time USD to EUR exchange rate."""
        fallback_rate = 0.95
        api_url = "https://api.frankfurter.app/latest?from=USD&to=EUR"

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            response = await self._http_client.get(api_url)
            response.raise_for_status()
            data = response.json()
            return float(data["rates"]["EUR"])
        except Exception as error:
            logger.warning(f"[AAVE][SENTINEL] FX API Error: {error}. Using fallback {fallback_rate}.")
            return fallback_rate

    def _ray_to_apy(self, ray_value: int) -> float:
        """Convert Aave RAY (1e27) to float APY."""
        if ray_value == 0:
            return 0.0
        rate_per_second = Decimal(ray_value) / RAY_UNITS / Decimal(SECONDS_PER_YEAR)
        return float((Decimal(1) + rate_per_second) ** Decimal(SECONDS_PER_YEAR) - Decimal(1))

    async def _safe_call(self, coro: Any, default: Any = None, label: str = "") -> Any:
        """Helper to execute an RPC call with simple error handling."""
        try:
            return await coro
        except Exception as error:
            logger.debug(f"[AAVE][RPC] Failed {label}: {error}")
            return default

    async def _scan_asset_details(self, asset_address: str, user_address: str) -> Optional[AaveAssetDetails]:
        """Worker to scan a single asset for balances, prices, and APYs."""
        async with self._semaphore:
            try:
                asset_address_checksum = AsyncWeb3.to_checksum_address(asset_address)

                reserve_data = await self._pool_contract.functions.getReserveData(asset_address_checksum).call()
                liquidity_rate_ray = reserve_data[2]
                variable_borrow_rate_ray = reserve_data[4]
                a_token_address = reserve_data[8]
                variable_debt_token_address = reserve_data[10]

                token_contract = self._web3_client.eth.contract(address=asset_address_checksum, abi=ERC20_ABI)
                a_token_contract = self._web3_client.eth.contract(address=a_token_address, abi=ERC20_ABI)
                debt_token_contract = self._web3_client.eth.contract(address=variable_debt_token_address, abi=ERC20_ABI)

                decimals = await self._safe_call(token_contract.functions.decimals().call(), None, "decimals")
                if decimals is None:
                    await asyncio.sleep(0.2)
                    decimals = await self._safe_call(token_contract.functions.decimals().call(), 18, "decimals_retry")

                balance_results = await asyncio.gather(
                    a_token_contract.functions.balanceOf(user_address).call(),
                    debt_token_contract.functions.balanceOf(user_address).call(),
                    token_contract.functions.balanceOf(user_address).call(),
                    return_exceptions=True
                )

                balance_supply = balance_results[0] if not isinstance(balance_results[0], Exception) else 0
                balance_debt = balance_results[1] if not isinstance(balance_results[1], Exception) else 0
                balance_wallet = balance_results[2] if not isinstance(balance_results[2], Exception) else 0

                symbol = await self._safe_call(token_contract.functions.symbol().call(), asset_address_checksum[:6], "symbol")
                price_raw = await self._safe_call(self._oracle_contract.functions.getAssetPrice(asset_address_checksum).call(), 0, "price")

                if symbol == "WAVAX":
                    try:
                        native_balance = await self._web3_client.eth.get_balance(user_address)
                        balance_wallet += native_balance
                    except Exception as error:
                        logger.warning(f"[AAVE][SCAN] Failed to fetch native AVAX balance: {error}")

                if balance_supply == 0 and balance_debt == 0 and balance_wallet == 0:
                    return None

                scale = 10 ** decimals
                normalized_supply = balance_supply / scale
                normalized_debt = balance_debt / scale
                normalized_wallet = balance_wallet / scale

                price_usd = price_raw / 1e8

                supply_value_usd = normalized_supply * price_usd
                debt_value_usd = normalized_debt * price_usd
                wallet_value_usd = normalized_wallet * price_usd

                logger.debug(
                    f"[AAVE][ASSET] {symbol}: "
                    f"Supply={normalized_supply:.4f} (${supply_value_usd:.2f}) | "
                    f"Debt={normalized_debt:.4f} (${debt_value_usd:.2f})"
                )

                return AaveAssetDetails(
                    symbol=str(symbol),
                    underlying_address=asset_address_checksum,
                    supply_amount=normalized_supply,
                    debt_amount=normalized_debt,
                    wallet_amount=normalized_wallet,
                    supply_value_usd=supply_value_usd,
                    debt_value_usd=debt_value_usd,
                    wallet_value_usd=wallet_value_usd,
                    supply_apy=self._ray_to_apy(liquidity_rate_ray),
                    borrow_apy=self._ray_to_apy(variable_borrow_rate_ray)
                )

            except Exception as error:
                logger.warning(f"[AAVE][SCAN] Skipped asset {asset_address}: {str(error)}")
                return None

    def _determine_strategy_and_liquidation(
        self,
        assets: List[AaveAssetDetails],
        health_factor: float
    ) -> Tuple[str, Optional[str], Optional[float], Optional[float]]:
        """
        Analyzes the portfolio to determine:
        1. Strategy: LONG or SHORT or NEUTRAL
        2. Main Risk Asset
        3. Liquidation Price for that asset
        """
        total_supply_usd = sum(a.supply_value_usd for a in assets)
        total_debt_usd = sum(a.debt_value_usd for a in assets)

        if total_supply_usd == 0 or total_debt_usd == 0:
            return "NEUTRAL", None, None, None

        stable_debt_usd = sum(a.debt_value_usd for a in assets if a.symbol in STABLECOIN_SYMBOLS)
        volatile_debt_usd = total_debt_usd - stable_debt_usd

        is_long = stable_debt_usd > volatile_debt_usd
        strategy = "LONG" if is_long else "SHORT"

        target_assets = []
        if is_long:
            target_assets = [a for a in assets if a.symbol not in STABLECOIN_SYMBOLS and a.supply_value_usd > 0]
            if not target_assets:
                return "NEUTRAL", None, None, None
            main_asset = max(target_assets, key=lambda x: x.supply_value_usd)
        else:
            target_assets = [a for a in assets if a.symbol not in STABLECOIN_SYMBOLS and a.debt_value_usd > 0]
            if not target_assets:
                return "NEUTRAL", None, None, None
            main_asset = max(target_assets, key=lambda x: x.debt_value_usd)

        if is_long:
            if main_asset.supply_amount == 0:
                return strategy, main_asset.symbol, 0.0, 0.0
            current_price = main_asset.supply_value_usd / main_asset.supply_amount
            liq_price = current_price / health_factor if health_factor > 0 else 0.0
        else:
            if main_asset.debt_amount == 0:
                return strategy, main_asset.symbol, 0.0, 0.0
            current_price = main_asset.debt_value_usd / main_asset.debt_amount
            liq_price = current_price * health_factor

        return strategy, main_asset.symbol, current_price, liq_price

    async def _fetch_position_snapshot(self) -> Optional[AavePositionSnapshot]:
        """Queries Aave Pool for Health Factor and Auto-Discovers all positions."""
        try:
            await self._initialize_resources()
            if not self._wallet_address or not self._pool_contract:
                return None

            user_address_checksum = AsyncWeb3.to_checksum_address(self._wallet_address)

            account_data = await self._pool_contract.functions.getUserAccountData(user_address_checksum).call()
            total_collateral_usd = account_data[0] / 1e8
            total_debt_usd = account_data[1] / 1e8
            raw_health_factor = account_data[5]

            health_factor = 999.0
            MAX_UINT256 = 2**255 - 1
            if raw_health_factor < MAX_UINT256:
                health_factor = raw_health_factor / 1e18

            logger.debug(f"[AAVE][GLOBAL] HF: {health_factor:.2f} | Collateral: ${total_collateral_usd:.2f} | Debt: ${total_debt_usd:.2f}")

            reserves_list = await self._pool_contract.functions.getReservesList().call()
            tasks = [self._scan_asset_details(address, user_address_checksum) for address in reserves_list]
            results = await asyncio.gather(*tasks)

            valid_assets = [result for result in results if result is not None]
            valid_assets.sort(key=lambda x: (x.supply_value_usd + x.wallet_value_usd), reverse=True)

            strategy, main_sym, main_price, liq_price = self._determine_strategy_and_liquidation(valid_assets, health_factor)

            return AavePositionSnapshot(
                health_factor=health_factor,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                strategy=strategy,
                main_asset_symbol=main_sym,
                main_asset_price=main_price,
                liquidation_price_usd=liq_price,
                assets=valid_assets
            )

        except Exception as error:
            logger.error(f"[AAVE][SENTINEL] Failed to fetch position snapshot: {error}")
            return None

    async def _format_notification_message(self, snapshot: AavePositionSnapshot) -> str:
        """Generates a detailed, readable status report for Telegram."""
        usd_to_eur_rate = await self._fetch_usd_eur_rate()

        def format_money(amount_usd: float) -> str:
            value_eur = amount_usd * usd_to_eur_rate
            return f"{format_currency(value_eur, 'EUR')} ({format_currency(amount_usd)})"

        pnl_text = "N/A"
        if self._initial_basis_usd is not None:
            current_total_equity = snapshot.total_strategy_equity_usd
            diff_usd = current_total_equity - self._initial_basis_usd
            percentage = 0.0
            if self._initial_basis_usd != 0:
                percentage = diff_usd / abs(self._initial_basis_usd)

            icon = "🚀" if diff_usd >= 0 else "🔻"
            pnl_text = f"{icon} {format_money(diff_usd)} ({format_percent(percentage)})"

        def format_asset_line(symbol: str, amount: float, value_usd: float, apy: Optional[float] = None) -> str:
            line = f"  • {symbol}: {amount:.4f} ({format_money(value_usd)})"
            if apy is not None:
                line += f" @ {format_percent(apy)} APY"
            return line

        supply_lines = [
            format_asset_line(a.symbol, a.supply_amount, a.supply_value_usd, a.supply_apy)
            for a in snapshot.assets if a.supply_value_usd > 1.0
        ]
        debt_lines = [
            format_asset_line(a.symbol, a.debt_amount, a.debt_value_usd, a.borrow_apy)
            for a in snapshot.assets if a.debt_value_usd > 1.0
        ]
        wallet_lines = [
            format_asset_line(a.symbol, a.wallet_amount, a.wallet_value_usd)
            for a in snapshot.assets if a.wallet_value_usd > 1.0
        ]

        supply_str = "\n".join(supply_lines) or "  (Aucun)"
        debt_str = "\n".join(debt_lines) or "  (Aucune)"
        wallet_str = "\n".join(wallet_lines) or "  (Vide)"

        hf = snapshot.health_factor
        if hf >= settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
            hf_emoji = "🟢"
        elif hf >= settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            hf_emoji = "⚪"
        elif hf >= settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
            hf_emoji = "🟡"
        elif hf >= settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
            hf_emoji = "🟠"
        else:
            hf_emoji = "🔴"

        strategy_block = ""
        if snapshot.strategy != "NEUTRAL" and snapshot.main_asset_symbol and snapshot.liquidation_price_usd:
            current_p = snapshot.main_asset_price or 0.0
            liq_p = snapshot.liquidation_price_usd

            dist_pct = 0.0
            if current_p > 0:
                dist_pct = abs(current_p - liq_p) / current_p

            direction_arrow = "📉" if snapshot.strategy == "LONG" else "📈"

            strategy_block = (
                f"\n**Stratégie**\n"
                f"**----------**\n"
                f"🎯 Type : **{snapshot.strategy}** sur {snapshot.main_asset_symbol}\n"
                f"💲 Prix actuel : `{format_currency(current_p)}`\n"
                f"💀 Liquidation : `{format_currency(liq_p)}`\n"
                f"📏 Distance : **{format_percent(dist_pct)}** {direction_arrow}\n"
            )

        return (
            f"**Statut du compte**\n"
            f"**----------**\n"
            f"🏥 Santé : `{hf:.2f}` {hf_emoji}\n"
            f"⚡ Levier : `x{snapshot.current_leverage:.2f}`\n"
            f"💎 Net Aave : `{format_money(snapshot.aave_net_worth_usd)}`\n"
            f"💰 Net Total : `{format_money(snapshot.total_strategy_equity_usd)}`\n"
            f"💵 PnL Latent : {pnl_text}\n"
            f"{strategy_block}\n"
            f"**Positions Aave**\n"
            f"**----------**\n"
            f"📈 Supply Total : `{format_money(snapshot.total_collateral_usd)}`\n"
            f"{supply_str}\n\n"

            f"📉 Dette Totale : `{format_money(snapshot.total_debt_usd)}`\n"
            f"{debt_str}\n\n"

            f"**Wallet (Bag)**\n"
            f"**----------**\n"
            f"💼 Total : `{format_money(snapshot.total_wallet_usd)}`\n"
            f"{wallet_str}\n\n"

            f"**Performance**\n"
            f"**----------**\n"
            f"📊 Net APY : `{format_percent(snapshot.weighted_net_apy)}`\n"
            f"💰 Initial : `{format_money(self._initial_basis_usd or 0.0)}`"
        )

    async def _evaluate_risk_and_notify(self, snapshot: AavePositionSnapshot) -> None:
        """
        Anti-Spam Logic:
        Decides whether to alert based on status changes, significant deviations, or heartbeats.
        """
        current_time = datetime.now()
        hf = snapshot.health_factor
        equity = snapshot.total_strategy_equity_usd

        current_status = "OPTIMAL"
        if hf < settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
            current_status = "CRITICAL"
        elif hf < settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
            current_status = "DANGER"
        elif hf < settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            current_status = "WARNING"
        elif hf < settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
            current_status = "NEUTRAL"
        else:
            current_status = "OPTIMAL"

        should_alert = False
        alert_level = "INFO"
        alert_title = ""

        if current_status != self._state.last_status_level:
            should_alert = True
            if current_status == "OPTIMAL":
                alert_level = "SUCCESS"
                alert_title = "🎯 Target Atteinte (Zone Verte)"
            elif current_status == "NEUTRAL":
                if self._state.last_status_level == "OPTIMAL":
                     alert_level = "INFO"
                     alert_title = "📉 Sortie de zone verte"
                else:
                     alert_level = "SUCCESS"
                     alert_title = "✅ Retour au calme (Zone Neutre)"
            elif current_status in ("WARNING", "DANGER", "CRITICAL"):
                alert_level = current_status
                alert_title = f"⚠️ Statut : {current_status}"

        elif current_status in ("WARNING", "DANGER", "CRITICAL") and self._state.last_health_factor:
            deviation = self._state.last_health_factor - hf
            if deviation > settings.AAVE_SIGNIFICANT_DEVIATION_HF:
                should_alert = True
                alert_level = current_status
                alert_title = f"📉 Chute rapide du HF (-{deviation:.2f})"

        elif self._state.last_total_equity_usd:
            equity_diff = self._state.last_total_equity_usd - equity
            equity_pct_drop = equity_diff / self._state.last_total_equity_usd if self._state.last_total_equity_usd > 0 else 0

            if equity_pct_drop > settings.AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT:
                should_alert = True
                alert_level = "WARNING"
                alert_title = f"💸 Chute brutale de la valeur (-{format_percent(equity_pct_drop)})"

        elif self._state.last_notification_time:
            elapsed = (current_time - self._state.last_notification_time).total_seconds()
            if elapsed > settings.AAVE_ALERT_COOLDOWN_SECONDS and current_status != "OPTIMAL":
                should_alert = True
                alert_level = "INFO" if current_status == "NEUTRAL" else current_status
                alert_title = f"⏰ Rappel : Statut {current_status}"

        if should_alert:
            message = await self._format_notification_message(snapshot)
            await self._send_telegram_alert(alert_title, message, alert_level)

            self._state.last_notification_time = current_time
            self._state.last_status_level = current_status

        self._state.last_health_factor = hf
        self._state.last_total_equity_usd = equity

        if not should_alert:
             self._state.last_status_level = current_status

    async def _execute_emergency_rescue(self) -> None:
        """Executes the rescue protocol: Approves and Supplies USDC to the Aave Pool."""
        logger.critical("[AAVE][SENTINEL] INITIATING EMERGENCY RESCUE PROTOCOL")

        if not self._web3_client or not self._usdc_contract or not self._pool_contract:
            await self._initialize_resources()

        assert self._web3_client is not None
        assert self._usdc_contract is not None
        assert self._pool_contract is not None
        assert self._private_key is not None

        account: LocalAccount = self._web3_client.eth.account.from_key(self._private_key)
        sender_address = account.address

        try:
            user_data = await self._pool_contract.functions.getUserAccountData(sender_address).call()
            total_debt_base = float(user_data[1])

            usdc_balance_wei = await self._usdc_contract.functions.balanceOf(sender_address).call()
            usdc_balance_float = usdc_balance_wei / 1e6

            required_collateral_base = (settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT * total_debt_base) / settings.AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD
            required_usdc_float = required_collateral_base / 100.0
            required_usdc_float *= 1.01

            amount_to_inject_float = min(required_usdc_float, usdc_balance_float, settings.AAVE_RESCUE_MAX_CAP_USDC)

            if amount_to_inject_float < settings.AAVE_RESCUE_MIN_AMOUNT_USDC:
                logger.warning(f"[AAVE][SENTINEL] Rescue amount too small ({amount_to_inject_float} USDC). Skipping.")
                return

            amount_wei = int(amount_to_inject_float * 1e6)

            if settings.PAPER_MODE:
                await self._send_telegram_alert(
                    "Simulation de sauvetage",
                    f"Mode papier actif.\n"
                    f"Injection calculée : **{amount_to_inject_float:.2f} USDC**\n"
                    f"(Cible: +{settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT} HF | Dispo: {usdc_balance_float:.2f} USDC)",
                    "CRITICAL"
                )
                return

            if not self._private_key:
                logger.error("[AAVE][SENTINEL] Abort rescue: Missing private key.")
                await self._send_telegram_alert("Echec du sauvetage", "Clé privée manquante !", "CRITICAL")
                return

            await self._send_telegram_alert(
                "Sauvetage en cours",
                f"Injection de **{amount_to_inject_float:.2f} USDC** pour remonter le HF de +{settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT}.",
                "CRITICAL"
            )

            nonce = await self._web3_client.eth.get_transaction_count(sender_address)
            gas_price = await self._web3_client.eth.gas_price
            adjusted_gas_price = int(gas_price * 1.1)

            approve_tx: TxParams = await self._usdc_contract.functions.approve(
                settings.AAVE_POOL_V3_ADDRESS, amount_wei
            ).build_transaction({
                'from': sender_address,
                'nonce': nonce,
                'gas': 80000,
                'gasPrice': adjusted_gas_price
            })
            signed_approve = self._web3_client.eth.account.sign_transaction(approve_tx, self._private_key)
            await self._web3_client.eth.send_raw_transaction(signed_approve.rawTransaction)

            await asyncio.sleep(2)

            supply_tx: TxParams = await self._pool_contract.functions.supply(
                settings.AAVE_USDC_ADDRESS, amount_wei, sender_address, 0
            ).build_transaction({
                'from': sender_address,
                'nonce': nonce + 1,
                'gas': 350000,
                'gasPrice': adjusted_gas_price
            })
            signed_supply = self._web3_client.eth.account.sign_transaction(supply_tx, self._private_key)
            tx_hash = await self._web3_client.eth.send_raw_transaction(signed_supply.rawTransaction)

            await self._send_telegram_alert("Sauvetage réussi", f"Montant: `{amount_to_inject_float:.2f} USDC`\nTX: `{tx_hash.hex()}`", "SUCCESS")

        except Exception as error:
            logger.critical(f"[AAVE][SENTINEL] Rescue transaction failed: {error}")
            await self._send_telegram_alert("Echec critique", f"Erreur : {str(error)}", "CRITICAL")

    async def start(self) -> None:
        """
        Starts the monitoring loop.
        Processes Telegram commands continuously (fast loop) and updates metrics periodically (slow loop).
        """
        self.is_running = True
        await self._initialize_resources()

        mode_label = "PAPER MODE" if settings.PAPER_MODE else "LIVE TRADING"
        logger.info(f"[AAVE][SENTINEL] Service started [{mode_label}]. Watching: {self._wallet_address}")

        await self._register_bot_commands()

        initial_snapshot = await self._fetch_position_snapshot()

        if initial_snapshot:
            details = await self._format_notification_message(initial_snapshot)
            await self._send_telegram_alert("Sentinel Démarré", f"Mode : {mode_label}\n\n{details}", "INFO")

            self._state.last_health_factor = initial_snapshot.health_factor
            self._state.last_total_equity_usd = initial_snapshot.total_strategy_equity_usd

            hf = initial_snapshot.health_factor
            if hf < settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
                self._state.last_status_level = "CRITICAL"
            elif hf < settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
                self._state.last_status_level = "DANGER"
            elif hf < settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
                self._state.last_status_level = "WARNING"
            elif hf < settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
                self._state.last_status_level = "NEUTRAL"
            else:
                self._state.last_status_level = "OPTIMAL"
        else:
            await self._send_telegram_alert("Sentinel Démarré", f"Mode : {mode_label}\n\n⚠️ Impossible de récupérer le snapshot initial.", "WARNING")

        last_metric_update_time = datetime.min

        while self.is_running:
            try:
                await self._process_telegram_commands()

                now = datetime.now()
                time_since_update = (now - last_metric_update_time).total_seconds()

                if time_since_update > settings.AAVE_REPORTING_INTERVAL_SECONDS:
                    snapshot = await self._fetch_position_snapshot()
                    last_metric_update_time = now

                    if snapshot:
                        logger.debug(f"[AAVE][SENTINEL] Tick HF: {snapshot.health_factor:.4f}")

                        await self._evaluate_risk_and_notify(snapshot)

                        if snapshot.health_factor < settings.AAVE_HEALTH_FACTOR_EMERGENCY_THRESHOLD:
                            await self._execute_emergency_rescue()
                            await asyncio.sleep(600)

            except Exception as loop_error:
                logger.error(f"[AAVE][SENTINEL] Loop error: {loop_error}")

            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stops the monitoring loop and cleans up resources."""
        self.is_running = False
        if self._http_client:
            await self._http_client.aclose()
        logger.info("[AAVE][SENTINEL] Service stopped.")


sentinel = AaveSentinelService()
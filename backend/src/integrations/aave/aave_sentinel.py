from __future__ import annotations

import asyncio
import html
from datetime import datetime
from decimal import Decimal
from typing import Optional

import httpx
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract
from web3.types import TxParams

from src.api.websocket.websocket_hub import schedule_full_recompute_broadcast
from src.configuration.config import settings
from src.core.structures.structures import DcaOrderStatus
from src.core.utils.format_utils import format_currency, format_percent
from src.integrations.aave.aave_abis import (
    AAVE_POOL_ABI,
    ADDRESS_PROVIDER_ABI,
    AAVE_ORACLE_ABI,
    ERC20_ABI,
    RAY_UNITS,
    SECONDS_PER_YEAR
)
from src.integrations.aave.aave_structures import AaveAssetDetails, AavePositionSnapshot, SentinelState
from src.integrations.telegram.telegram_client import edit_message_text
from src.logging.logger import get_application_logger
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.db import DatabaseSessionLocal

logger = get_application_logger(__name__)

Account.enable_unaudited_hdwallet_features()

STABLECOIN_SYMBOLS: set[str] = {"USDC", "USDC.e", "USDT", "USDt", "DAI", "FRAX", "MIM", "BUSD"}


class AaveSentinelService:
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
        if not settings.WALLET_MNEMONIC:
            logger.warning("[AAVE][SENTINEL][CREDENTIALS] Configuration missing: WALLET_MNEMONIC not set. Operation restricted.")
            return

        try:
            account_instance: LocalAccount = Account.from_mnemonic(
                mnemonic=settings.WALLET_MNEMONIC,
                account_path=f"m/44'/60'/0'/0/{settings.WALLET_DERIVATION_INDEX}"
            )
            self._private_key = account_instance.key.hex()
            self._wallet_address = account_instance.address
            logger.info("[AAVE][SENTINEL][CREDENTIALS] Wallet loaded successfully: %s", self._wallet_address)

        except Exception as credential_error:
            logger.exception("[AAVE][SENTINEL][CREDENTIALS] Credential derivation failed: %s", credential_error)

    async def _initialize_resources(self) -> None:
        if not self._private_key:
            self._derive_credentials()

        if not self._web3_client:
            from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
            self._web3_client = resolve_async_web3_provider_for_chain("avalanche")

            pool_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
            self._pool_contract = self._web3_client.eth.contract(address=pool_contract_address, abi=AAVE_POOL_ABI)

            usdc_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_USDC_ADDRESS)
            self._usdc_contract = self._web3_client.eth.contract(address=usdc_contract_address, abi=ERC20_ABI)

            try:
                addresses_provider_address = await self._pool_contract.functions.ADDRESSES_PROVIDER().call()
                addresses_provider_contract = self._web3_client.eth.contract(address=addresses_provider_address, abi=ADDRESS_PROVIDER_ABI)
                oracle_contract_address = await addresses_provider_contract.functions.getPriceOracle().call()
                self._oracle_contract = self._web3_client.eth.contract(address=oracle_contract_address, abi=AAVE_ORACLE_ABI)
                logger.debug("[AAVE][SENTINEL][INITIALIZATION] Oracle successfully identified at address: %s", oracle_contract_address)
            except Exception as initialization_error:
                logger.exception("[AAVE][SENTINEL][INITIALIZATION] Failed to initialize Price Oracle contract: %s", initialization_error)

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=10.0)

    async def _send_telegram_alert(self, title: str, message: str, severity_level: str = "INFO") -> None:
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.debug("[AAVE][SENTINEL][TELEGRAM] Alert suppressed: Telegram credentials not configured")
            return

        severity_emoji_mapping = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "DANGER": "🚨",
            "SUCCESS": "✅",
            "CRITICAL": "💀"
        }

        current_timestamp_string = datetime.now().strftime("%H:%M:%S")
        formatted_full_title = f"{severity_emoji_mapping.get(severity_level, 'ℹ️')} {title} ({current_timestamp_string})"

        telegram_api_endpoint_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        html_formatted_body = f"<b>{html.escape(formatted_full_title)}</b>\n\n{message}"

        request_payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": html_formatted_body,
            "parse_mode": "HTML"
        }

        try:
            if self._http_client:
                await self._http_client.post(telegram_api_endpoint_url, json=request_payload)
                logger.info("[AAVE][SENTINEL][TELEGRAM] Alert successfully dispatched: %s", title)
        except Exception as dispatch_error:
            logger.exception("[AAVE][SENTINEL][TELEGRAM] Failed to dispatch Telegram alert: %s", dispatch_error)

    async def _register_bot_commands(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.debug("[AAVE][SENTINEL][TELEGRAM] Bot command registration skipped: token missing")
            return

        command_registration_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setMyCommands"

        defined_commands = [
            {"command": "snapshot", "description": "📸 Afficher le statut du portefeuille"},
        ]

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            command_registration_response = await self._http_client.post(command_registration_url, json={"commands": defined_commands})

            if command_registration_response.status_code == 200 and command_registration_response.json().get("ok"):
                logger.info("[AAVE][SENTINEL][TELEGRAM] Bot commands registered successfully")
            else:
                logger.warning("[AAVE][SENTINEL][TELEGRAM] Bot command registration rejected by API: %s", command_registration_response.text)

        except Exception as registration_error:
            logger.warning("[AAVE][SENTINEL][TELEGRAM] Error encountered during bot command registration: %s", registration_error)

    async def _process_telegram_commands(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            return

        update_polling_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"

        polling_payload = {
            "offset": self._last_telegram_update_id + 1,
            "allowed_updates": ["message", "callback_query"],
            "timeout": 0
        }

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            polling_response = await self._http_client.post(update_polling_url, json=polling_payload)

            if polling_response.status_code != 200:
                logger.debug("[AAVE][SENTINEL][TELEGRAM] Update polling returned non-200 status: %d", polling_response.status_code)
                return

            polling_data = polling_response.json()
            if not polling_data.get("ok"):
                logger.warning("[AAVE][SENTINEL][TELEGRAM] Update polling failed according to API response")
                return

            received_updates = polling_data.get("result", [])
            for telegram_update in received_updates:
                update_identifier = telegram_update.get("update_id")
                self._last_telegram_update_id = update_identifier

                if "message" in telegram_update:
                    received_message = telegram_update.get("message", {})
                    message_text = received_message.get("text", "").strip()

                    if message_text == "/snapshot":
                        logger.info("[AAVE][SENTINEL][TELEGRAM] Manual snapshot requested by user")
                        await self._send_telegram_alert("Snapshot Demandé", "📸 Calcul du snapshot en cours...", "INFO")

                        current_position_snapshot = await self._fetch_position_snapshot()
                        if current_position_snapshot:
                            formatted_alert_message = await self._format_notification_message(current_position_snapshot)
                            await self._send_telegram_alert("Snapshot Manuel", formatted_alert_message, "INFO")
                        else:
                            await self._send_telegram_alert("Erreur", "Impossible de récupérer les données Aave.", "WARNING")

                elif "callback_query" in telegram_update:
                    await self._handle_callback_query(telegram_update["callback_query"])

        except Exception as processing_error:
            logger.debug("[AAVE][SENTINEL][TELEGRAM] Error encountered during update processing: %s", processing_error)

    async def _handle_callback_query(self, callback_query_data: dict) -> None:
        interaction_callback_data = callback_query_data.get("data", "")
        origin_message = callback_query_data.get("message", {})
        origin_message_identifier = origin_message.get("message_id")

        if not interaction_callback_data or not origin_message_identifier:
            logger.warning("[AAVE][SENTINEL][CALLBACK] Received malformed callback query update")
            return

        if interaction_callback_data.startswith("approve_dca:") or interaction_callback_data.startswith("reject_dca:"):
            target_order_identifier = int(interaction_callback_data.split(":")[1])
            is_approval_action = interaction_callback_data.startswith("approve_dca:")
            resolved_order_status = DcaOrderStatus.APPROVED if is_approval_action else DcaOrderStatus.REJECTED
            status_display_label = "APPROUVÉ ✅" if is_approval_action else "REJETÉ ❌"

            logger.info("[AAVE][SENTINEL][CALLBACK] Processing interaction [%s] for order identifier %s", status_display_label, target_order_identifier)

            with DatabaseSessionLocal() as database_session:
                order_dao = DcaOrderDao(database_session)
                strategy_dao = DcaStrategyDao(database_session)

                target_dca_order = order_dao.retrieve_by_id(target_order_identifier)

                if target_dca_order:
                    target_dca_order.order_status = resolved_order_status.value
                    order_dao.save(target_dca_order)
                    database_session.commit()

                    from src.core.dca.dca_manager import DcaManager
                    dca_manager_instance = DcaManager(database_session)
                    strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)

                    if strategy_instance:
                        base_message_details = dca_manager_instance._generate_approval_message_body(target_dca_order, strategy_instance)
                        full_confirmation_message = f"{base_message_details}✨ <b>Statut:</b> {status_display_label}"

                        edit_message_text(
                            message_id=origin_message_identifier,
                            text=full_confirmation_message
                        )
                    else:
                        edit_message_text(
                            message_id=origin_message_identifier,
                            text=f"✅ Ordre #{target_order_identifier} {status_display_label} avec succès."
                        )

                    schedule_full_recompute_broadcast()
                    logger.info("[AAVE][SENTINEL][CALLBACK] Order identifier %s successfully transitioned to status %s", target_order_identifier, resolved_order_status.name)
                else:
                    logger.error("[AAVE][SENTINEL][CALLBACK] Target order identifier %s not found in persistence layer", target_order_identifier)

    async def _fetch_usd_eur_exchange_rate(self) -> float:
        default_fallback_rate = 0.95
        fx_provider_api_url = "https://api.frankfurter.dev/v1/latest?from=USD&to=EUR"

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            fx_api_response = await self._http_client.get(fx_provider_api_url)
            fx_api_response.raise_for_status()
            api_response_data = fx_api_response.json()
            return float(api_response_data["rates"]["EUR"])
        except Exception as exchange_rate_error:
            logger.warning("[AAVE][SENTINEL][FX] Exchange rate provider unavailable: %s. Defaulting to fallback rate: %0.2f", exchange_rate_error, default_fallback_rate)
            return default_fallback_rate

    def _convert_ray_to_annual_percentage_yield(self, ray_value: int) -> float:
        if ray_value == 0:
            return 0.0
        interest_rate_per_second = Decimal(ray_value) / RAY_UNITS / Decimal(SECONDS_PER_YEAR)
        return float((Decimal(1) + interest_rate_per_second) ** Decimal(SECONDS_PER_YEAR) - Decimal(1))

    async def _perform_protected_onchain_call(self, coroutine_operation: any, fallback_default_value: any = None, operation_label: str = "") -> any:
        try:
            return await coroutine_operation
        except Exception as rpc_error:
            logger.debug("[AAVE][SENTINEL][RPC] On-chain operation [%s] failed: %s", operation_label, rpc_error)
            return fallback_default_value

    async def _scan_individual_asset_details(self, asset_contract_address: str, target_user_address: str) -> Optional[AaveAssetDetails]:
        async with self._semaphore:
            try:
                asset_address_checksum = AsyncWeb3.to_checksum_address(asset_contract_address)

                reserve_configuration_data = await self._pool_contract.functions.getReserveData(asset_address_checksum).call()
                liquidity_rate_ray = reserve_configuration_data[2]
                variable_borrow_rate_ray = reserve_configuration_data[4]
                a_token_contract_address = reserve_configuration_data[8]
                variable_debt_token_contract_address = reserve_configuration_data[10]

                underlying_token_contract = self._web3_client.eth.contract(address=asset_address_checksum, abi=ERC20_ABI)
                a_token_contract_instance = self._web3_client.eth.contract(address=a_token_contract_address, abi=ERC20_ABI)
                debt_token_contract_instance = self._web3_client.eth.contract(address=variable_debt_token_contract_address, abi=ERC20_ABI)

                asset_decimal_precision = await self._perform_protected_onchain_call(underlying_token_contract.functions.decimals().call(), None, "fetch_decimals")
                if asset_decimal_precision is None:
                    await asyncio.sleep(0.2)
                    asset_decimal_precision = await self._perform_protected_onchain_call(underlying_token_contract.functions.decimals().call(), 18, "retry_fetch_decimals")

                balance_fetch_coroutine = asyncio.gather(
                    a_token_contract_instance.functions.balanceOf(target_user_address).call(),
                    debt_token_contract_instance.functions.balanceOf(target_user_address).call(),
                    underlying_token_contract.functions.balanceOf(target_user_address).call(),
                    return_exceptions=True
                )
                raw_balance_results = await balance_fetch_coroutine

                token_supply_balance = raw_balance_results[0] if not isinstance(raw_balance_results[0], Exception) else 0
                token_debt_balance = raw_balance_results[1] if not isinstance(raw_balance_results[1], Exception) else 0
                token_wallet_balance = raw_balance_results[2] if not isinstance(raw_balance_results[2], Exception) else 0

                asset_ticker_symbol = await self._perform_protected_onchain_call(underlying_token_contract.functions.symbol().call(), str(asset_address_checksum)[:6], "fetch_symbol")
                raw_asset_price_unit_base = await self._perform_protected_onchain_call(self._oracle_contract.functions.getAssetPrice(asset_address_checksum).call(), 0, "fetch_oracle_price")

                if asset_ticker_symbol == "WAVAX":
                    try:
                        native_blockchain_balance = await self._web3_client.eth.get_balance(target_user_address)
                        token_wallet_balance += native_blockchain_balance
                    except Exception as balance_fetch_error:
                        logger.warning("[AAVE][SENTINEL][SCAN] Failed to aggregate native AVAX balance: %s", balance_fetch_error)

                if token_supply_balance == 0 and token_debt_balance == 0 and token_wallet_balance == 0:
                    return None

                normalization_scale_factor = 10 ** asset_decimal_precision
                normalized_supply_amount = token_supply_balance / normalization_scale_factor
                normalized_debt_amount = token_debt_balance / normalization_scale_factor
                normalized_wallet_amount = token_wallet_balance / normalization_scale_factor

                unit_price_usd = raw_asset_price_unit_base / 1e8

                total_supply_value_usd = normalized_supply_amount * unit_price_usd
                total_debt_value_usd = normalized_debt_amount * unit_price_usd
                total_wallet_value_usd = normalized_wallet_amount * unit_price_usd

                logger.debug("[AAVE][SENTINEL][SCAN] Asset Details Resolved [%s]: Supply=$%0.2f, Debt=$%0.2f", asset_ticker_symbol, total_supply_value_usd, total_debt_value_usd)

                return AaveAssetDetails(
                    symbol=str(asset_ticker_symbol),
                    underlying_address=asset_address_checksum,
                    supply_amount=normalized_supply_amount,
                    debt_amount=normalized_debt_amount,
                    wallet_amount=normalized_wallet_amount,
                    supply_value_usd=total_supply_value_usd,
                    debt_value_usd=total_debt_value_usd,
                    wallet_value_usd=total_wallet_value_usd,
                    supply_apy=self._convert_ray_to_annual_percentage_yield(liquidity_rate_ray),
                    borrow_apy=self._convert_ray_to_annual_percentage_yield(variable_borrow_rate_ray)
                )

            except Exception as scanning_error:
                logger.warning("[AAVE][SENTINEL][SCAN] Skipping asset registration for address %s due to error: %s", asset_contract_address, scanning_error)
                return None

    def _determine_position_strategy_and_liquidation_metrics(
            self,
            detected_assets: list[AaveAssetDetails],
            current_health_factor: float
    ) -> tuple[str, Optional[str], Optional[float], Optional[float]]:
        aggregate_supply_value_usd = sum(asset.supply_value_usd for asset in detected_assets)
        aggregate_debt_value_usd = sum(asset.debt_value_usd for asset in detected_assets)

        if aggregate_supply_value_usd == 0 or aggregate_debt_value_usd == 0:
            return "NEUTRAL", None, None, None

        stablecoin_debt_value_usd = sum(asset.debt_value_usd for asset in detected_assets if asset.symbol in STABLECOIN_SYMBOLS)
        volatile_asset_debt_value_usd = aggregate_debt_value_usd - stablecoin_debt_value_usd

        is_long_biased_strategy = stablecoin_debt_value_usd > volatile_asset_debt_value_usd
        resolved_strategy_direction = "LONG" if is_long_biased_strategy else "SHORT"

        eligible_strategy_assets = []
        if is_long_biased_strategy:
            eligible_strategy_assets = [asset for asset in detected_assets if asset.symbol not in STABLECOIN_SYMBOLS and asset.supply_value_usd > 0]
            if not eligible_strategy_assets:
                return "NEUTRAL", None, None, None
            primary_exposure_asset = max(eligible_strategy_assets, key=lambda asset: asset.supply_value_usd)
        else:
            eligible_strategy_assets = [asset for asset in detected_assets if asset.symbol not in STABLECOIN_SYMBOLS and asset.debt_value_usd > 0]
            if not eligible_strategy_assets:
                return "NEUTRAL", None, None, None
            primary_exposure_asset = max(eligible_strategy_assets, key=lambda asset: asset.debt_value_usd)

        if is_long_biased_strategy:
            if primary_exposure_asset.supply_amount == 0:
                return resolved_strategy_direction, primary_exposure_asset.symbol, 0.0, 0.0
            asset_current_unit_price = primary_exposure_asset.supply_value_usd / primary_exposure_asset.supply_amount
            calculated_liquidation_price_usd = asset_current_unit_price / current_health_factor if current_health_factor > 0 else 0.0
        else:
            if primary_exposure_asset.debt_amount == 0:
                return resolved_strategy_direction, primary_exposure_asset.symbol, 0.0, 0.0
            asset_current_unit_price = primary_exposure_asset.debt_value_usd / primary_exposure_asset.debt_amount
            calculated_liquidation_price_usd = asset_current_unit_price * current_health_factor

        return resolved_strategy_direction, primary_exposure_asset.symbol, asset_current_unit_price, calculated_liquidation_price_usd

    async def _fetch_position_snapshot(self) -> Optional[AavePositionSnapshot]:
        try:
            await self._initialize_resources()
            if not self._wallet_address or not self._pool_contract:
                logger.error("[AAVE][SENTINEL][SNAPSHOT] Aborting snapshot fetch: initialization incomplete")
                return None

            user_account_address_checksum = AsyncWeb3.to_checksum_address(self._wallet_address)

            aggregate_account_metrics_data = await self._pool_contract.functions.getUserAccountData(user_account_address_checksum).call()
            total_collateral_value_usd = aggregate_account_metrics_data[0] / 1e8
            total_debt_value_usd = aggregate_account_metrics_data[1] / 1e8
            raw_health_factor_unit_base = aggregate_account_metrics_data[5]

            normalized_health_factor = 999.0
            maximum_unsigned_integer_limit = 2 ** 255 - 1
            if raw_health_factor_unit_base < maximum_unsigned_integer_limit:
                normalized_health_factor = raw_health_factor_unit_base / 1e18

            logger.debug("[AAVE][SENTINEL][SNAPSHOT] Core Metrics - HF: %0.2f, Collateral: $%0.2f, Debt: $%0.2f", normalized_health_factor, total_collateral_value_usd, total_debt_value_usd)

            global_reserves_inventory = await self._pool_contract.functions.getReservesList().call()
            asset_scanning_tasks = [self._scan_individual_asset_details(reserve_address, user_account_address_checksum) for reserve_address in global_reserves_inventory]
            scanning_task_results = await asyncio.gather(*asset_scanning_tasks)

            identified_active_assets = [result for result in scanning_task_results if result is not None]
            identified_active_assets.sort(key=lambda asset: (asset.supply_value_usd + asset.wallet_value_usd), reverse=True)

            strategy_direction, primary_asset_ticker, primary_asset_market_price, strategy_liquidation_threshold_price = self._determine_position_strategy_and_liquidation_metrics(identified_active_assets, normalized_health_factor)

            return AavePositionSnapshot(
                health_factor=normalized_health_factor,
                total_collateral_usd=total_collateral_value_usd,
                total_debt_usd=total_debt_value_usd,
                strategy=strategy_direction,
                main_asset_symbol=primary_asset_ticker,
                main_asset_price=primary_asset_market_price,
                liquidation_price_usd=strategy_liquidation_threshold_price,
                assets=identified_active_assets
            )

        except Exception as snapshot_fetch_error:
            logger.exception("[AAVE][SENTINEL][SNAPSHOT] Critical failure during position snapshot acquisition: %s", snapshot_fetch_error)
            return None

    async def _format_notification_message(self, position_snapshot: AavePositionSnapshot) -> str:
        current_usd_to_eur_exchange_rate = await self._fetch_usd_eur_exchange_rate()

        def _format_monetary_values(amount_in_usd: float) -> str:
            equivalent_value_in_eur = amount_in_usd * current_usd_to_eur_exchange_rate
            return f"{format_currency(equivalent_value_in_eur, 'EUR')} ({format_currency(amount_in_usd)})"

        performance_pnl_display_text = "N/A"
        if self._initial_basis_usd is not None:
            current_total_position_equity = position_snapshot.total_strategy_equity_usd
            equity_absolute_difference_usd = current_total_position_equity - self._initial_basis_usd
            equity_percentage_variance = 0.0
            if self._initial_basis_usd != 0:
                equity_percentage_variance = equity_absolute_difference_usd / abs(self._initial_basis_usd)

            trend_visual_indicator = "🚀" if equity_absolute_difference_usd >= 0 else "🔻"
            performance_pnl_display_text = f"{trend_visual_indicator} {_format_monetary_values(equity_absolute_difference_usd)} ({format_percent(equity_percentage_variance)})"

        def _format_asset_inventory_line(asset_ticker: str, unit_amount: float, value_in_usd: float, annual_yield_percentage: Optional[float] = None) -> str:
            inventory_line_content = f"  • {asset_ticker}: {unit_amount:.4f} ({_format_monetary_values(value_in_usd)})"
            if annual_yield_percentage is not None:
                inventory_line_content += f" @ {format_percent(annual_yield_percentage)} APY"
            return inventory_line_content

        supply_inventory_lines = [
            _format_asset_inventory_line(asset.symbol, asset.supply_amount, asset.supply_value_usd, asset.supply_apy)
            for asset in position_snapshot.assets if asset.supply_value_usd > 1.0
        ]
        debt_inventory_lines = [
            _format_asset_inventory_line(asset.symbol, asset.debt_amount, asset.debt_value_usd, asset.borrow_apy)
            for asset in position_snapshot.assets if asset.debt_value_usd > 1.0
        ]
        wallet_inventory_lines = [
            _format_asset_inventory_line(asset.symbol, asset.wallet_amount, asset.wallet_value_usd)
            for asset in position_snapshot.assets if asset.wallet_value_usd > 1.0
        ]

        formatted_supply_section_string = "\n".join(supply_inventory_lines) or "  (Aucun)"
        formatted_debt_section_string = "\n".join(debt_inventory_lines) or "  (Aucune)"
        formatted_wallet_section_string = "\n".join(wallet_inventory_lines) or "  (Vide)"

        current_health_factor_value = position_snapshot.health_factor
        if current_health_factor_value >= settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
            health_factor_indicator_emoji = "🟢"
        elif current_health_factor_value >= settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            health_factor_indicator_emoji = "⚪"
        elif current_health_factor_value >= settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
            health_factor_indicator_emoji = "🟡"
        elif current_health_factor_value >= settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
            health_factor_indicator_emoji = "🟠"
        else:
            health_factor_indicator_emoji = "🔴"

        active_strategy_context_block = ""
        if position_snapshot.strategy != "NEUTRAL" and position_snapshot.main_asset_symbol and position_snapshot.liquidation_price_usd:
            current_market_unit_price = position_snapshot.main_asset_price or 0.0
            calculated_liquidation_price_usd = position_snapshot.liquidation_price_usd

            price_distance_to_liquidation_percentage = 0.0
            if current_market_unit_price > 0:
                price_distance_to_liquidation_percentage = abs(current_market_unit_price - calculated_liquidation_price_usd) / current_market_unit_price

            volatility_direction_arrow_emoji = "📉" if position_snapshot.strategy == "LONG" else "📈"

            active_strategy_context_block = (
                "\n<b>Stratégie</b>\n"
                "<b>----------</b>\n"
                f"🎯 Type : <b>{position_snapshot.strategy}</b> sur {position_snapshot.main_asset_symbol}\n"
                f"💲 Prix actuel : <code>{format_currency(current_market_unit_price)}</code>\n"
                f"💀 Liquidation : <code>{format_currency(calculated_liquidation_price_usd)}</code>\n"
                f"📏 Distance : <b>{format_percent(price_distance_to_liquidation_percentage)}</b> {volatility_direction_arrow_emoji}\n"
            )

        return (
            "<b>Statut du compte</b>\n"
            "<b>----------</b>\n"
            f"🏥 Santé : <code>{current_health_factor_value:.2f}</code> {health_factor_indicator_emoji}\n"
            f"⚡ Levier : <code>x{position_snapshot.current_leverage:.2f}</code>\n"
            f"💎 Net Aave : <code>{_format_monetary_values(position_snapshot.aave_net_worth_usd)}</code>\n"
            f"💰 Net Total : <code>{_format_monetary_values(position_snapshot.total_strategy_equity_usd)}</code>\n"
            f"💵 PnL Latent : {performance_pnl_display_text}\n"
            f"{active_strategy_context_block}\n"
            "<b>Positions Aave</b>\n"
            "<b>----------</b>\n"
            f"📈 Supply Total : <code>{_format_monetary_values(position_snapshot.total_collateral_usd)}</code>\n"
            f"{formatted_supply_section_string}\n\n"

            f"📉 Dette Totale : <code>{_format_monetary_values(position_snapshot.total_debt_usd)}</code>\n"
            f"{formatted_debt_section_string}\n\n"

            "<b>Wallet (Bag)</b>\n"
            "<b>----------</b>\n"
            f"💼 Total : <code>{_format_monetary_values(position_snapshot.total_wallet_usd)}</code>\n"
            f"{formatted_wallet_section_string}\n\n"

            "<b>Performance</b>\n"
            "<b>----------</b>\n"
            f"📊 Net APY : <code>{format_percent(position_snapshot.weighted_net_apy)}</code>\n"
            f"💰 Initial : <code>{_format_monetary_values(self._initial_basis_usd or 0.0)}</code>"
        )

    async def _evaluate_risk_and_notify(self, position_snapshot: AavePositionSnapshot) -> None:
        evaluation_timestamp = datetime.now()
        current_health_factor = position_snapshot.health_factor
        current_strategy_equity = position_snapshot.total_strategy_equity_usd

        resolved_risk_status_level = "OPTIMAL"
        if current_health_factor < settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
            resolved_risk_status_level = "CRITICAL"
        elif current_health_factor < settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
            resolved_risk_status_level = "DANGER"
        elif current_health_factor < settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
            resolved_risk_status_level = "WARNING"
        elif current_health_factor < settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
            resolved_risk_status_level = "NEUTRAL"

        is_notification_dispatch_required = False
        notification_severity_level = "INFO"
        notification_title_content = ""

        if resolved_risk_status_level != self._state.last_status_level:
            is_notification_dispatch_required = True
            if resolved_risk_status_level == "OPTIMAL":
                notification_severity_level = "SUCCESS"
                notification_title_content = "🎯 Target Atteinte (Zone Verte)"
            elif resolved_risk_status_level == "NEUTRAL":
                if self._state.last_status_level == "OPTIMAL":
                    notification_severity_level = "INFO"
                    notification_title_content = "📉 Sortie de zone verte"
                else:
                    notification_severity_level = "SUCCESS"
                    notification_title_content = "✅ Retour au calme (Zone Neutre)"
            elif resolved_risk_status_level in ("WARNING", "DANGER", "CRITICAL"):
                notification_severity_level = resolved_risk_status_level
                notification_title_content = f"⚠️ Statut : {resolved_risk_status_level}"

        elif resolved_risk_status_level in ("WARNING", "DANGER", "CRITICAL") and self._state.last_health_factor:
            health_factor_volatility_deviation = self._state.last_health_factor - current_health_factor
            if health_factor_volatility_deviation > settings.AAVE_SIGNIFICANT_DEVIATION_HF:
                is_notification_dispatch_required = True
                notification_severity_level = resolved_risk_status_level
                notification_title_content = f"📉 Chute rapide du HF (-{health_factor_volatility_deviation:.2f})"

        elif self._state.last_total_equity_usd:
            equity_absolute_difference = self._state.last_total_equity_usd - current_strategy_equity
            equity_drawdown_percentage = equity_absolute_difference / self._state.last_total_equity_usd if self._state.last_total_equity_usd > 0 else 0

            if equity_drawdown_percentage > settings.AAVE_SIGNIFICANT_DEVIATION_EQUITY_PCT:
                is_notification_dispatch_required = True
                notification_severity_level = "WARNING"
                notification_title_content = f"💸 Chute brutale de la valeur (-{format_percent(equity_drawdown_percentage)})"

        elif self._state.last_notification_time:
            seconds_elapsed_since_last_dispatch = (evaluation_timestamp - self._state.last_notification_time).total_seconds()
            if seconds_elapsed_since_last_dispatch > settings.AAVE_ALERT_COOLDOWN_SECONDS and resolved_risk_status_level != "OPTIMAL":
                is_notification_dispatch_required = True
                notification_severity_level = "INFO" if resolved_risk_status_level == "NEUTRAL" else resolved_risk_status_level
                notification_title_content = f"⏰ Rappel : Statut {resolved_risk_status_level}"

        if is_notification_dispatch_required:
            detailed_alert_message_body = await self._format_notification_message(position_snapshot)
            await self._send_telegram_alert(notification_title_content, detailed_alert_message_body, notification_severity_level)

            self._state.last_notification_time = evaluation_timestamp
            self._state.last_status_level = resolved_risk_status_level

        self._state.last_health_factor = current_health_factor
        self._state.last_total_equity_usd = current_strategy_equity

        if not is_notification_dispatch_required:
            self._state.last_status_level = resolved_risk_status_level

    async def _initiate_onchain_emergency_rescue_protocol(self) -> None:
        logger.critical("[AAVE][SENTINEL][RESCUE] INITIATING EMERGENCY LIQUIDITY INJECTION PROTOCOL")

        if not self._web3_client or not self._usdc_contract or not self._pool_contract:
            await self._initialize_resources()

        assert self._web3_client is not None
        assert self._usdc_contract is not None
        assert self._pool_contract is not None
        assert self._private_key is not None

        rescue_signer_account: LocalAccount = self._web3_client.eth.account.from_key(self._private_key)
        rescue_sender_address = rescue_signer_account.address

        try:
            account_data_tuple = await self._pool_contract.functions.getUserAccountData(rescue_sender_address).call()
            total_liabilities_base_units = float(account_data_tuple[1])

            available_usdc_balance_wei = await self._usdc_contract.functions.balanceOf(rescue_sender_address).call()
            available_usdc_balance_float_units = available_usdc_balance_wei / 1e6

            required_rescue_collateral_base_units = (settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT * total_liabilities_base_units) / settings.AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD
            required_liquidity_injection_usdc_float = (required_rescue_collateral_base_units / 100.0) * 1.01

            calculated_injection_amount_usdc_float = min(required_liquidity_injection_usdc_float, available_usdc_balance_float_units, settings.AAVE_RESCUE_MAX_CAP_USDC)

            if calculated_injection_amount_usdc_float < settings.AAVE_RESCUE_MIN_AMOUNT_USDC:
                logger.warning("[AAVE][SENTINEL][RESCUE] Aborting action: calculated rescue amount %0.2f USDC is below safety threshold", calculated_injection_amount_usdc_float)
                return

            injection_amount_in_wei_units = int(calculated_injection_amount_usdc_float * 1e6)

            if settings.PAPER_MODE:
                await self._send_telegram_alert(
                    "Simulation de sauvetage",
                    f"Mode papier actif.\n"
                    f"Injection calculée : <b>{calculated_injection_amount_usdc_float:.2f} USDC</b>\n"
                    f"(Cible: +{settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT} HF | Dispo: {available_usdc_balance_float_units:.2f} USDC)",
                    "CRITICAL"
                )
                logger.info("[AAVE][SENTINEL][RESCUE] Paper Mode active: emergency rescue protocol simulation complete")
                return

            await self._send_telegram_alert(
                "Sauvetage en cours",
                f"Injection de <b>{calculated_injection_amount_usdc_float:.2f} USDC</b> pour remonter le HF de +{settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT}.",
                "CRITICAL"
            )

            current_account_nonce = await self._web3_client.eth.get_transaction_count(rescue_sender_address)
            current_market_gas_price = await self._web3_client.eth.gas_price
            scaled_aggressive_gas_price = int(current_market_gas_price * 1.1)

            token_approval_transaction_payload: TxParams = await self._usdc_contract.functions.approve(
                settings.AAVE_POOL_V3_ADDRESS, injection_amount_in_wei_units
            ).build_transaction({
                'from': rescue_sender_address,
                'nonce': current_account_nonce,
                'gas': 80000,
                'gasPrice': scaled_aggressive_gas_price
            })
            signed_approval_transaction_blob = self._web3_client.eth.account.sign_transaction(token_approval_transaction_payload, self._private_key)
            await self._web3_client.eth.send_raw_transaction(signed_approval_transaction_blob.rawTransaction)

            await asyncio.sleep(2)

            liquidity_supply_transaction_payload: TxParams = await self._pool_contract.functions.supply(
                settings.AAVE_USDC_ADDRESS, injection_amount_in_wei_units, rescue_sender_address, 0
            ).build_transaction({
                'from': rescue_sender_address,
                'nonce': current_account_nonce + 1,
                'gas': 350000,
                'gasPrice': scaled_aggressive_gas_price
            })
            signed_supply_transaction_blob = self._web3_client.eth.account.sign_transaction(liquidity_supply_transaction_payload, self._private_key)
            broadcast_transaction_hash = await self._web3_client.eth.send_raw_transaction(signed_supply_transaction_blob.rawTransaction)

            await self._send_telegram_alert("Sauvetage réussi", f"Montant: <code>{calculated_injection_amount_usdc_float:.2f} USDC</code>\nTX: <code>{broadcast_transaction_hash.hex()}</code>", "SUCCESS")
            logger.info("[AAVE][SENTINEL][RESCUE] Emergency rescue protocol successfully finalized: %s", broadcast_transaction_hash.hex())

        except Exception as rescue_protocol_error:
            logger.critical("[AAVE][SENTINEL][RESCUE] Critical failure during emergency rescue protocol execution: %s", rescue_protocol_error)
            await self._send_telegram_alert("Echec critique", f"Erreur : {str(rescue_protocol_error)}", "CRITICAL")

    async def start(self) -> None:
        self.is_running = True
        await self._initialize_resources()

        operating_mode_display_label = "PAPER MODE" if settings.PAPER_MODE else "LIVE TRADING"
        logger.info("[AAVE][SENTINEL][LIFECYCLE] Service initialization complete [%s]. Monitoring wallet: %s", operating_mode_display_label, self._wallet_address)

        await self._register_bot_commands()

        initialization_position_snapshot = await self._fetch_position_snapshot()

        if initialization_position_snapshot:
            detailed_initial_snapshot_markdown = await self._format_notification_message(initialization_position_snapshot)
            await self._send_telegram_alert("Sentinel Démarré", f"Mode : {operating_mode_display_label}\n\n{detailed_initial_snapshot_markdown}", "INFO")

            self._state.last_health_factor = initialization_position_snapshot.health_factor
            self._state.last_total_equity_usd = initialization_position_snapshot.total_strategy_equity_usd

            initial_health_factor_value = initialization_position_snapshot.health_factor
            if initial_health_factor_value < settings.AAVE_HEALTH_FACTOR_DANGER_THRESHOLD:
                self._state.last_status_level = "CRITICAL"
            elif initial_health_factor_value < settings.AAVE_HEALTH_FACTOR_WARNING_THRESHOLD:
                self._state.last_status_level = "DANGER"
            elif initial_health_factor_value < settings.AAVE_HEALTH_FACTOR_NEUTRAL_THRESHOLD:
                self._state.last_status_level = "WARNING"
            elif initial_health_factor_value < settings.AAVE_HEALTH_FACTOR_RELOOP_THRESHOLD:
                self._state.last_status_level = "NEUTRAL"
            else:
                self._state.last_status_level = "OPTIMAL"
        else:
            await self._send_telegram_alert("Sentinel Démarré", f"Mode : {operating_mode_display_label}\n\n⚠️ Impossible de récupérer le snapshot initial.", "WARNING")

        last_monitoring_cycle_update_timestamp = datetime.min

        while self.is_running:
            try:
                await self._process_telegram_commands()

                current_loop_iteration_timestamp = datetime.now()
                seconds_elapsed_since_last_cycle = (current_loop_iteration_timestamp - last_monitoring_cycle_update_timestamp).total_seconds()

                if seconds_elapsed_since_last_cycle > settings.AAVE_REPORTING_INTERVAL_SECONDS:
                    cyclic_monitoring_snapshot = await self._fetch_position_snapshot()
                    last_monitoring_cycle_update_timestamp = current_loop_iteration_timestamp

                    if cyclic_monitoring_snapshot:
                        logger.debug("[AAVE][SENTINEL][LIFECYCLE] Periodic monitoring check active. Current Health Factor: %0.4f", cyclic_monitoring_snapshot.health_factor)

                        await self._evaluate_risk_and_notify(cyclic_monitoring_snapshot)

                        if cyclic_monitoring_snapshot.health_factor < settings.AAVE_HEALTH_FACTOR_EMERGENCY_THRESHOLD:
                            await self._initiate_onchain_emergency_rescue_protocol()
                            await asyncio.sleep(600)

            except Exception as service_loop_error:
                logger.exception("[AAVE][SENTINEL][LIFECYCLE] Unexpected error encountered during monitoring loop: %s", service_loop_error)

            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.is_running = False
        if self._http_client:
            await self._http_client.aclose()
        logger.info("[AAVE][SENTINEL][LIFECYCLE] Service shutdown sequence initiated")


sentinel = AaveSentinelService()

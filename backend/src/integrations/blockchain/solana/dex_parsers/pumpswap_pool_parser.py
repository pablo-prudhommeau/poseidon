import base64
import struct
from typing import Optional, Tuple

import base58

from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals, rpc_get_multiple_accounts
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class PumpswapPoolParser:
    PUMPSWAP_TOKEN_MINT_OFFSET = 43
    PUMPSWAP_SOL_MINT_OFFSET = 75
    PUMPSWAP_TOKEN_VAULT_OFFSET = 139
    PUMPSWAP_SOL_VAULT_OFFSET = 171

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[Tuple[float, str]]:
        try:
            if len(account_data) < 203:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Invalid account data length")
                return None

            token_mint = base58.b58encode(account_data[self.PUMPSWAP_TOKEN_MINT_OFFSET:self.PUMPSWAP_TOKEN_MINT_OFFSET + 32]).decode("ascii")
            sol_mint = base58.b58encode(account_data[self.PUMPSWAP_SOL_MINT_OFFSET:self.PUMPSWAP_SOL_MINT_OFFSET + 32]).decode("ascii")

            token_vault = base58.b58encode(account_data[self.PUMPSWAP_TOKEN_VAULT_OFFSET:self.PUMPSWAP_TOKEN_VAULT_OFFSET + 32]).decode("ascii")
            sol_vault = base58.b58encode(account_data[self.PUMPSWAP_SOL_VAULT_OFFSET:self.PUMPSWAP_SOL_VAULT_OFFSET + 32]).decode("ascii")

            vault_accounts_response = rpc_get_multiple_accounts(rpc_url, [token_vault, sol_vault])
            if not vault_accounts_response or len(vault_accounts_response) < 2:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Failed to fetch vault accounts")
                return None

            token_vault_data = vault_accounts_response[0]
            sol_vault_data = vault_accounts_response[1]

            if not token_vault_data or not sol_vault_data:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] One or more vault accounts are empty")
                return None

            token_vault_decoded = base64.b64decode(token_vault_data["data"][0])
            sol_vault_decoded = base64.b64decode(sol_vault_data["data"][0])

            if len(token_vault_decoded) < 72 or len(sol_vault_decoded) < 72:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Vault account data too short")
                return None

            token_vault_balance = struct.unpack_from("<Q", token_vault_decoded, 64)[0]
            sol_vault_balance = struct.unpack_from("<Q", sol_vault_decoded, 64)[0]

            if token_vault_balance == 0 or sol_vault_balance == 0:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Vault balances are zero")
                return None

            decimals_token = get_spl_token_decimals(rpc_url, token_mint)
            decimals_sol = get_spl_token_decimals(rpc_url, sol_mint)

            if decimals_token is None or decimals_sol is None:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Failed to fetch decimals for %s or %s", token_mint[:8], sol_mint[:8])
                return None

            adjusted_token_reserves = token_vault_balance / (10 ** decimals_token)
            adjusted_sol_reserves = sol_vault_balance / (10 ** decimals_sol)

            price_in_sol = adjusted_sol_reserves / adjusted_token_reserves

            target_is_token = target_token_address == token_mint
            if target_is_token:
                return price_in_sol, sol_mint

            if price_in_sol <= 0:
                return None

            return 1.0 / price_in_sol, token_mint

        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Error parsing pool data")
            return None

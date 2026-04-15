from __future__ import annotations

from typing import Optional

import requests

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

JUPITER_PRICE_API_URL = "https://api.jup.ag/price/v3"
JUPITER_PRICE_TIMEOUT_SECONDS = 5


def read_solana_pool_price_usd(
        pool_address: str,
        target_token_address: str,
        dex_id: str = "unknown",
) -> Optional[float]:
    try:
        response = requests.get(
            JUPITER_PRICE_API_URL,
            params={"ids": target_token_address},
            timeout=JUPITER_PRICE_TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            logger.warning("[BLOCKCHAIN][PRICE][SOL] Jupiter HTTP %d for %s (%s) — %s", response.status_code, target_token_address[:8], dex_id, response.text)
            return None

        response_json = response.json()
        token_data_raw = response_json.get(target_token_address)

        if token_data_raw is None:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] Jupiter returned no data for %s (%s)", target_token_address[:8], dex_id)
            return None

        from src.integrations.blockchain.solana.solana_structures import JupiterPriceData
        token_price_data = JupiterPriceData.model_validate(token_data_raw)

        if token_price_data.usdPrice <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] Jupiter returned zero price for %s (%s)", target_token_address[:8], dex_id)
            return None

        logger.debug("[BLOCKCHAIN][PRICE][SOL] %s (%s) = %.10f USD via Jupiter V3", target_token_address[:8], dex_id, token_price_data.usdPrice)
        return token_price_data.usdPrice

    except Exception:
        logger.exception("[BLOCKCHAIN][PRICE][SOL] Jupiter price fetch failed for %s (%s)", target_token_address[:8], dex_id)
        return None


def read_solana_pool_prices_usd_batch(token_addresses: list[str]) -> dict[str, float]:
    """
    Fetch multiple token prices in a single call to avoid hitting the 1 req/sec rate limit.
    """
    if not token_addresses:
        return {}

    try:
        unique_tokens = list(set(token_addresses))
        max_batch_size = 50
        results: dict[str, float] = {}

        for i in range(0, len(unique_tokens), max_batch_size):
            batch = unique_tokens[i:i + max_batch_size]
            tokens_str = ",".join(batch)

            response = requests.get(
                JUPITER_PRICE_API_URL,
                params={"ids": tokens_str},
                timeout=JUPITER_PRICE_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                logger.warning("[BLOCKCHAIN][PRICE][SOL] Jupiter batch HTTP %d — %s", response.status_code, response.text)
                continue

            response_json = response.json()
            from src.integrations.blockchain.solana.solana_structures import JupiterPriceData

            for token_address in batch:
                token_data_raw = response_json.get(token_address)
                if token_data_raw is not None:
                    try:
                        token_price_data = JupiterPriceData.model_validate(token_data_raw)
                        if token_price_data.usdPrice > 0:
                            results[token_address] = token_price_data.usdPrice
                    except Exception:
                        pass

        return results

    except Exception:
        logger.exception("[BLOCKCHAIN][PRICE][SOL] Jupiter batch price fetch failed")
        return {}

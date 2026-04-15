from __future__ import annotations

import base64
from typing import Optional

import requests

from src.integrations.blockchain.solana.blockchain_solana_signer import SolanaSigner, build_default_solana_signer
from src.integrations.blockchain.solana.solana_structures import (
    JupiterQuoteResponse,
    JupiterSwapRequest,
    JupiterSwapResponse,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

JUPITER_QUOTE_API_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API_URL = "https://quote-api.jup.ag/v6/swap"
JUPITER_API_TIMEOUT_SECONDS = 10

WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterSwapExecutor:
    def __init__(self, solana_signer: Optional[SolanaSigner] = None) -> None:
        self._solana_signer = solana_signer

    def _ensure_signer(self) -> SolanaSigner:
        if self._solana_signer is None:
            self._solana_signer = build_default_solana_signer()
        return self._solana_signer

    def fetch_quote(
            self,
            input_mint: str,
            output_mint: str,
            amount_lamports: int,
            slippage_bps: int = 50,
    ) -> Optional[JupiterQuoteResponse]:
        try:
            response = requests.get(
                JUPITER_QUOTE_API_URL,
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(amount_lamports),
                    "slippageBps": str(slippage_bps),
                },
                timeout=JUPITER_API_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                logger.warning("[BLOCKCHAIN][JUPITER][QUOTE] HTTP %d — %s → %s", response.status_code, input_mint[:8], output_mint[:8])
                return None

            quote = JupiterQuoteResponse.model_validate(response.json())
            logger.info(
                "[BLOCKCHAIN][JUPITER][QUOTE] %s → %s — in=%s out=%s impact=%s%%",
                input_mint[:8], output_mint[:8], quote.inAmount, quote.outAmount, quote.priceImpactPct,
            )
            return quote

        except Exception:
            logger.exception("[BLOCKCHAIN][JUPITER][QUOTE] Failed for %s → %s", input_mint[:8], output_mint[:8])
            return None

    def execute_swap(self, quote: JupiterQuoteResponse) -> Optional[str]:
        signer = self._ensure_signer()
        wallet_public_key = signer.address

        swap_request = JupiterSwapRequest(
            quoteResponse=quote,
            userPublicKey=wallet_public_key,
        )

        try:
            response = requests.post(
                JUPITER_SWAP_API_URL,
                json=swap_request.model_dump(),
                timeout=JUPITER_API_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                logger.warning("[BLOCKCHAIN][JUPITER][SWAP] HTTP %d — wallet=%s", response.status_code, wallet_public_key[:8])
                return None

            swap_response = JupiterSwapResponse.model_validate(response.json())
            serialized_transaction_bytes = base64.b64decode(swap_response.swapTransaction)

            logger.info(
                "[BLOCKCHAIN][JUPITER][SWAP] Transaction built (%d bytes) — signing and broadcasting",
                len(serialized_transaction_bytes),
            )

            signature = signer.send_raw_transaction(serialized_transaction_bytes)
            logger.info("[BLOCKCHAIN][JUPITER][SWAP] Broadcast success — signature=%s", signature)
            return signature

        except Exception:
            logger.exception("[BLOCKCHAIN][JUPITER][SWAP] Failed for wallet %s", wallet_public_key[:8])
            return None

    def buy_token_with_sol(
            self,
            target_token_address: str,
            sol_amount_lamports: int,
            slippage_bps: int = 50,
    ) -> Optional[str]:
        logger.info(
            "[BLOCKCHAIN][JUPITER][BUY] SOL → %s — amount=%d lamports slippage=%d bps",
            target_token_address[:8], sol_amount_lamports, slippage_bps,
        )

        quote = self.fetch_quote(
            input_mint=WRAPPED_SOL_MINT,
            output_mint=target_token_address,
            amount_lamports=sol_amount_lamports,
            slippage_bps=slippage_bps,
        )

        if quote is None:
            logger.warning("[BLOCKCHAIN][JUPITER][BUY] No quote available for %s", target_token_address[:8])
            return None

        return self.execute_swap(quote)

    def sell_token_for_sol(
            self,
            source_token_address: str,
            token_amount_raw: int,
            slippage_bps: int = 50,
    ) -> Optional[str]:
        logger.info(
            "[BLOCKCHAIN][JUPITER][SELL] %s → SOL — amount=%d raw slippage=%d bps",
            source_token_address[:8], token_amount_raw, slippage_bps,
        )

        quote = self.fetch_quote(
            input_mint=source_token_address,
            output_mint=WRAPPED_SOL_MINT,
            amount_lamports=token_amount_raw,
            slippage_bps=slippage_bps,
        )

        if quote is None:
            logger.warning("[BLOCKCHAIN][JUPITER][SELL] No quote available for %s", source_token_address[:8])
            return None

        return self.execute_swap(quote)

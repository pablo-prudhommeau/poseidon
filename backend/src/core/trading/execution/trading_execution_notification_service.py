from __future__ import annotations

from src.integrations.telegram.telegram_client import send_alert
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def dispatch_position_dust_remaining_alert(
        token_symbol: str,
        token_mint_address: str,
        remaining_balance_raw: int,
        token_decimals: int,
        position_id: int,
) -> None:
    remaining_quantity_human = remaining_balance_raw / float(10 ** token_decimals)
    send_alert(
        title=f"Trading position dust remaining — {token_symbol}",
        body=(
            f"Position: {position_id}\n"
            f"Token mint: {token_mint_address}\n"
            f"Remaining balance: {remaining_quantity_human:.12f} tokens ({remaining_balance_raw} raw units)\n"
            "The token account rent may remain locked until the dust is cleared."
        ),
        emoji_indicator="⚠️",
    )
    logger.warning(
        "[TRADING][EXECUTION][POSITION][DUST] Dust remaining after full close — "
        "position_id=%s token_symbol=%s token_mint_address=%s remaining_balance_raw=%d",
        position_id,
        token_symbol,
        token_mint_address,
        remaining_balance_raw,
    )

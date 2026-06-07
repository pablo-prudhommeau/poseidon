from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

import src.integrations.jupiter.jupiter_client as jupiter_client_module
from src.integrations.jupiter.jupiter_client import fetch_jupiter_quote, resolve_sol_usd_price
from src.integrations.jupiter.jupiter_structures import (
    JupiterApiFailureReason,
    JupiterApiUnavailableError,
    JupiterQuoteResponse,
)


def _build_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.jup.ag/swap/v1/quote")
    response = httpx.Response(status_code=status_code, request=request, text="rate limited")
    return httpx.HTTPStatusError("rate limited", request=request, response=response)


@patch("src.integrations.jupiter.jupiter_client.httpx.Client")
def test_fetch_jupiter_quote_rate_limited_raises_without_error_log(
        httpx_client_class_mock: MagicMock,
        caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    http_client = MagicMock()
    httpx_client_class_mock.return_value.__enter__.return_value = http_client
    http_client.get.side_effect = _build_http_status_error(429)

    with pytest.raises(JupiterApiUnavailableError) as jupiter_error:
        fetch_jupiter_quote(
            input_mint="input-mint",
            output_mint="output-mint",
            amount_in_lamports=1_000_000,
            slippage_basis_points=100,
        )

    assert jupiter_error.value.failure_reason == JupiterApiFailureReason.RATE_LIMITED
    error_log_records = [log_record for log_record in caplog.records if log_record.levelno >= logging.ERROR]
    assert error_log_records == []


def _reset_jupiter_sol_usd_reference_cache() -> None:
    jupiter_client_module._cached_sol_usd_reference_price = None
    jupiter_client_module._cached_sol_usd_reference_timestamp = 0.0


@patch("src.integrations.jupiter.jupiter_client.get_spl_token_decimals", return_value=6)
@patch(
    "src.integrations.jupiter.jupiter_client.resolve_stablecoin_address_for_blockchain",
    return_value="Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
)
@patch("src.integrations.jupiter.jupiter_client.fetch_jupiter_quote")
def test_resolve_sol_usd_price_uses_jupiter_quote(
        fetch_jupiter_quote_mock: MagicMock,
        resolve_stablecoin_address_mock: MagicMock,
        get_spl_token_decimals_mock: MagicMock,
) -> None:
    _reset_jupiter_sol_usd_reference_cache()
    fetch_jupiter_quote_mock.return_value = JupiterQuoteResponse.model_validate({
        "inputMint": "So11111111111111111111111111111111111111112",
        "inAmount": "1000000000",
        "outputMint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "outAmount": "150000000",
        "otherAmountThreshold": "149000000",
        "swapMode": "ExactIn",
        "slippageBps": 50,
        "priceImpactPct": "0",
        "routePlan": [],
    })

    sol_usd_price = resolve_sol_usd_price()

    assert sol_usd_price == 150.0
    fetch_jupiter_quote_mock.assert_called_once()
    resolve_stablecoin_address_mock.assert_called_once()
    get_spl_token_decimals_mock.assert_called_once()


@patch("src.integrations.jupiter.jupiter_client.fetch_jupiter_quote")
def test_resolve_sol_usd_price_returns_none_when_jupiter_unavailable(
        fetch_jupiter_quote_mock: MagicMock,
) -> None:
    _reset_jupiter_sol_usd_reference_cache()
    fetch_jupiter_quote_mock.side_effect = JupiterApiUnavailableError(
        "unavailable",
        failure_reason=JupiterApiFailureReason.NETWORK_ERROR,
    )

    sol_usd_price = resolve_sol_usd_price()

    assert sol_usd_price is None

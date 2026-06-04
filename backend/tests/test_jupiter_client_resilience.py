from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.integrations.jupiter.jupiter_client import fetch_jupiter_quote
from src.integrations.jupiter.jupiter_structures import JupiterApiFailureReason, JupiterApiUnavailableError


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

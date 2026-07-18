from __future__ import annotations

FRANKFURTER_HISTORICAL_EURO_TO_USD_URL_TEMPLATE: str = (
    "https://api.frankfurter.dev/v1/{exchange_rate_date}?from=EUR&to=USD"
)
FRANKFURTER_LATEST_USD_TO_EURO_URL: str = "https://api.frankfurter.dev/v1/latest?from=USD&to=EUR"
FRANKFURTER_HTTP_TIMEOUT_SECONDS: float = 10.0

from __future__ import annotations

import logging
from typing import Protocol

from src.core.aavesentinel.aave_sentinel_structures import AaveSentinelConfigurationError

logger = logging.getLogger(__name__)

AAVE_SENTINEL_ENABLED_ENVIRONMENT_VARIABLE = "AAVE_SENTINEL_ENABLED"
ROUTESCAN_API_KEY_ENVIRONMENT_VARIABLE = "ROUTESCAN_API_KEY"


class AaveSentinelBootConfigurationSettings(Protocol):
    AAVE_SENTINEL_ENABLED: bool
    ROUTESCAN_API_KEY: str


def validate_aave_sentinel_configuration(
        configuration_settings: AaveSentinelBootConfigurationSettings,
) -> None:
    if not configuration_settings.AAVE_SENTINEL_ENABLED:
        return

    routescan_api_key: str = configuration_settings.ROUTESCAN_API_KEY.strip()
    if not routescan_api_key:
        raise AaveSentinelConfigurationError(
            f"{ROUTESCAN_API_KEY_ENVIRONMENT_VARIABLE} is required when "
            f"{AAVE_SENTINEL_ENABLED_ENVIRONMENT_VARIABLE}=true",
        )

    logger.info("[CONFIGURATION][AAVESENTINEL] Sentinel configuration validated")

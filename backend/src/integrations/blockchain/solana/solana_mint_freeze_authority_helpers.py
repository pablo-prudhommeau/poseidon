from __future__ import annotations

from typing import Optional

from src.integrations.blockchain.solana.solana_structures import (
    SolanaMintFreezeAuthoritySnapshot,
    SolanaParsedMintAccountInfo,
)


def parse_freeze_authority_from_account_info_value(account_info_value: Optional[dict]) -> Optional[str]:
    if account_info_value is None:
        return None

    data_payload = account_info_value.get("data")
    if not isinstance(data_payload, dict):
        return None

    parsed_payload = data_payload.get("parsed")
    if not isinstance(parsed_payload, dict):
        return None

    if parsed_payload.get("type") != "mint":
        return None

    info_payload = parsed_payload.get("info")
    if not isinstance(info_payload, dict):
        return None

    parsed_mint_account = SolanaParsedMintAccountInfo.model_validate(
        {"freeze_authority_address": info_payload.get("freezeAuthority")},
    )
    freeze_authority_address = parsed_mint_account.freeze_authority_address
    if freeze_authority_address is None:
        return None

    normalized_freeze_authority_address = freeze_authority_address.strip()
    if not normalized_freeze_authority_address:
        return None

    return normalized_freeze_authority_address


def build_solana_mint_freeze_authority_snapshot(
        mint_address: str,
        account_info_value: Optional[dict],
) -> SolanaMintFreezeAuthoritySnapshot:
    return SolanaMintFreezeAuthoritySnapshot(
        mint_address=mint_address,
        freeze_authority_address=parse_freeze_authority_from_account_info_value(account_info_value),
    )


def resolve_freeze_authority_address_from_snapshots(
        snapshots: list[SolanaMintFreezeAuthoritySnapshot],
        mint_address: str,
) -> Optional[str]:
    for snapshot in snapshots:
        if snapshot.mint_address == mint_address:
            return snapshot.freeze_authority_address
    return None


def is_solana_mint_blocked_by_freeze_authority_snapshot(
        snapshot: SolanaMintFreezeAuthoritySnapshot,
) -> bool:
    return snapshot.freeze_authority_address is not None

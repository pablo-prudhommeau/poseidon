from __future__ import annotations

from src.integrations.blockchain.solana.solana_mint_freeze_authority_helpers import (
    build_solana_mint_freeze_authority_snapshot,
    is_solana_mint_blocked_by_freeze_authority_snapshot,
    parse_freeze_authority_from_account_info_value,
    resolve_freeze_authority_address_from_snapshots,
)


def test_parse_freeze_authority_from_token_2022_mint_account() -> None:
    account_info_value = {
        "data": {
            "parsed": {
                "type": "mint",
                "info": {
                    "freezeAuthority": "BxJX29JYeYriDHH9u77fQ87K8DM8oWUfosuzFQYbkWBY",
                },
            },
        },
    }

    freeze_authority_address = parse_freeze_authority_from_account_info_value(account_info_value)

    assert freeze_authority_address == "BxJX29JYeYriDHH9u77fQ87K8DM8oWUfosuzFQYbkWBY"


def test_parse_freeze_authority_returns_none_when_revoked() -> None:
    account_info_value = {
        "data": {
            "parsed": {
                "type": "mint",
                "info": {
                    "freezeAuthority": None,
                },
            },
        },
    }

    freeze_authority_address = parse_freeze_authority_from_account_info_value(account_info_value)

    assert freeze_authority_address is None


def test_build_snapshot_marks_blocked_mint() -> None:
    account_info_value = {
        "data": {
            "parsed": {
                "type": "mint",
                "info": {
                    "freezeAuthority": "CreatorWallet1111111111111111111111111111",
                },
            },
        },
    }

    snapshot = build_solana_mint_freeze_authority_snapshot(
        mint_address="MintAddress1111111111111111111111111111",
        account_info_value=account_info_value,
    )

    assert is_solana_mint_blocked_by_freeze_authority_snapshot(snapshot) is True
    assert (
        resolve_freeze_authority_address_from_snapshots(
            snapshots=[snapshot],
            mint_address="MintAddress1111111111111111111111111111",
        )
        == "CreatorWallet1111111111111111111111111111"
    )

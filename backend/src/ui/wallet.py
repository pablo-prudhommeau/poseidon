
# src/ui/wallet.py
from __future__ import annotations
import os
from typing import Optional, Dict, Any

def get_wallet_address() -> str | None:
    return os.getenv("WALLET_ADDRESS") or None

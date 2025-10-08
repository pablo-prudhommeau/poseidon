from typing import Mapping, Sequence, Union, Optional


def _read_path(node: object, path: Sequence[Union[str, int]]) -> Optional[object]:
    """
    Traverse a nested structure of dicts/lists using a path of keys/indices.

    This confines all low-level dict/list access to a single helper, keeping the
    rest of the codebase typed and attribute-oriented (no widespread .get()).
    """
    current: object = node
    for part in path:
        if isinstance(part, int):
            if isinstance(current, list) and 0 <= part < len(current):
                current = current[part]
            else:
                return None
        else:
            if isinstance(current, Mapping) and part in current:
                current = current[part]  # confined indexing
            else:
                return None
    return current


def _read_str_field(mapping: Mapping[str, object], key: str) -> Optional[str]:
    """Return a string field if present and non-empty."""
    if key in mapping:
        value = mapping[key]
        if isinstance(value, str) and len(value) > 0:
            return value
    return None


def _read_int_like_field(mapping: Mapping[str, object], key: str) -> Optional[int]:
    """
    Return an integer field if present. Accepts:
    - int directly
    - decimal numeric string
    - hex string with '0x' prefix
    """
    if key not in mapping:
        return None
    raw = mapping[key]
    if isinstance(raw, int):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(raw, 16) if raw.startswith("0x") else int(raw)
        except Exception:
            return None
    try:
        return int(raw)
    except Exception:
        return None


def _normalize_value_wei(raw: Optional[int]) -> int:
    """Normalize optional integer to non-negative wei amount."""
    if raw is None:
        return 0
    return raw if raw > 0 else 0


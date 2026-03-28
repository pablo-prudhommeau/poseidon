from typing import Mapping, Sequence, Union, Optional


def _read_path(node: object, path: Sequence[Union[str, int]]) -> Optional[object]:
    current: object = node
    for part in path:
        if isinstance(part, int):
            if isinstance(current, list) and 0 <= part < len(current):
                current = current[part]
            else:
                return None
        else:
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return None
    return current


def _read_str_field(mapping: Mapping[str, object], key: str) -> Optional[str]:
    if key in mapping:
        value = mapping[key]
        if isinstance(value, str) and len(value) > 0:
            return value
    return None


def _read_int_like_field(mapping: Mapping[str, object], key: str) -> Optional[int]:
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
    if raw is None:
        return 0
    return raw if raw > 0 else 0

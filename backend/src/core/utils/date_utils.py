from datetime import datetime
from typing import Optional


def get_current_local_datetime() -> datetime:
    return datetime.now().astimezone()


def ensure_timezone_aware(target_datetime: Optional[datetime]) -> Optional[datetime]:
    if target_datetime is None:
        return None
    if target_datetime.tzinfo is None:
        return target_datetime.astimezone()
    return target_datetime


def format_datetime_to_local_iso(target_datetime: Optional[datetime]) -> Optional[str]:
    if target_datetime is None:
        return None

    return target_datetime.astimezone().isoformat()


def parse_iso_datetime_to_local(iso_datetime_text: str | None) -> datetime:
    if iso_datetime_text is None:
        raise ValueError("ISO datetime string is required")

    normalized_iso_datetime_text = iso_datetime_text.strip()
    if not normalized_iso_datetime_text:
        raise ValueError("ISO datetime string is empty")

    if normalized_iso_datetime_text.endswith("Z"):
        normalized_iso_datetime_text = f"{normalized_iso_datetime_text[:-1]}+00:00"

    try:
        parsed_datetime = datetime.fromisoformat(normalized_iso_datetime_text)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime string: {iso_datetime_text!r}") from exc

    if parsed_datetime.tzinfo is None:
        return parsed_datetime.astimezone()
    return parsed_datetime


def convert_epoch_to_local_datetime(epoch_timestamp: float | int) -> datetime:
    normalized_timestamp = float(epoch_timestamp)

    if normalized_timestamp > 1e18 or normalized_timestamp < -1e18:
        normalized_timestamp /= 1_000_000_000.0
    elif normalized_timestamp > 1e15 or normalized_timestamp < -1e15:
        normalized_timestamp /= 1_000_000.0
    elif normalized_timestamp > 1e11 or normalized_timestamp < -1e11:
        normalized_timestamp /= 1_000.0

    return datetime.fromtimestamp(normalized_timestamp).astimezone()

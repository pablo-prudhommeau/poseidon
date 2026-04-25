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


def convert_epoch_to_local_datetime(epoch_timestamp: float | int) -> datetime:
    normalized_timestamp = float(epoch_timestamp)

    if normalized_timestamp > 1e18 or normalized_timestamp < -1e18:
        normalized_timestamp /= 1_000_000_000.0
    elif normalized_timestamp > 1e15 or normalized_timestamp < -1e15:
        normalized_timestamp /= 1_000_000.0
    elif normalized_timestamp > 1e11 or normalized_timestamp < -1e11:
        normalized_timestamp /= 1_000.0

    return datetime.fromtimestamp(normalized_timestamp).astimezone()

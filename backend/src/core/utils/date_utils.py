from datetime import datetime


def timezone_now() -> datetime:
    return datetime.now().astimezone()


def epoch_to_local_datetime(epoch: float | int) -> datetime:
    if epoch > 1e18 or epoch < -1e18:
        epoch /= 1_000_000_000
    elif epoch > 1e15 or epoch < -1e15:
        epoch /= 1_000_000
    elif epoch > 1e11 or epoch < -1e11:
        epoch /= 1_000
    return datetime.fromtimestamp(epoch).astimezone()
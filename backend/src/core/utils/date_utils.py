from datetime import datetime


def timezone_now() -> datetime:
    return datetime.now().astimezone()

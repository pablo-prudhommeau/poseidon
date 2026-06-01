from __future__ import annotations

import asyncio
import sys
import threading
from types import TracebackType
from typing import Callable, Optional

from src.logging.incident_forwarding_service import (
    forward_asyncio_exception_context_to_telegram,
    forward_unhandled_exception_to_telegram,
)

_previous_sys_excepthook: Optional[Callable[[type[BaseException], BaseException, Optional[TracebackType]], None]] = None
_previous_threading_excepthook: Optional[
    Callable[[threading.ExceptHookArgs], None]
] = None
_asyncio_exception_hooks_installed = False


def install_application_exception_hooks() -> None:
    global _previous_sys_excepthook, _previous_threading_excepthook

    if _previous_sys_excepthook is None:
        _previous_sys_excepthook = sys.excepthook
        sys.excepthook = _sys_unhandled_exception_hook

    if hasattr(threading, "excepthook") and _previous_threading_excepthook is None:
        _previous_threading_excepthook = threading.excepthook
        threading.excepthook = _threading_unhandled_exception_hook


def install_asyncio_unhandled_exception_handler(event_loop: asyncio.AbstractEventLoop) -> None:
    global _asyncio_exception_hooks_installed

    if _asyncio_exception_hooks_installed:
        return

    previous_handler = event_loop.get_exception_handler()

    def asyncio_unhandled_exception_handler(
            loop: asyncio.AbstractEventLoop,
            context: dict[str, object],
    ) -> None:
        forward_asyncio_exception_context_to_telegram(context)
        if previous_handler is not None:
            previous_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    event_loop.set_exception_handler(asyncio_unhandled_exception_handler)
    _asyncio_exception_hooks_installed = True


def _sys_unhandled_exception_hook(
        exception_type: type[BaseException],
        exception_value: BaseException,
        exception_traceback: Optional[TracebackType],
) -> None:
    if not issubclass(exception_type, KeyboardInterrupt):
        forward_unhandled_exception_to_telegram(
            exception_type=exception_type,
            exception_value=exception_value,
            exception_traceback=exception_traceback,
            origin_label="sys.excepthook",
        )

    if _previous_sys_excepthook is not None:
        _previous_sys_excepthook(exception_type, exception_value, exception_traceback)


def _threading_unhandled_exception_hook(hook_arguments: threading.ExceptHookArgs) -> None:
    forward_unhandled_exception_to_telegram(
        exception_type=hook_arguments.exc_type,
        exception_value=hook_arguments.exc_value,
        exception_traceback=hook_arguments.exc_traceback,
        origin_label=f"threading.excepthook thread={hook_arguments.thread.name!r}",
    )

    if _previous_threading_excepthook is not None:
        _previous_threading_excepthook(hook_arguments)

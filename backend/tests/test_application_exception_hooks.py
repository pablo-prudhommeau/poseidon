from __future__ import annotations

from src.logging.application_exception_hooks import _is_benign_asyncio_connection_reset


class _ConnectionLostHandle:
    def __repr__(self) -> str:
        return "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>"


def test_connection_reset_during_transport_shutdown_is_ignored() -> None:
    context: dict[str, object] = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": ConnectionResetError(10054, "Une connexion existante a dû être fermée par l’hôte distant"),
        "handle": _ConnectionLostHandle(),
    }

    assert _is_benign_asyncio_connection_reset(context) is True


def test_connection_reset_outside_transport_shutdown_is_reported() -> None:
    context: dict[str, object] = {
        "message": "Exception in callback fetch_position_snapshot()",
        "exception": ConnectionResetError(10054, "reset"),
        "handle": None,
    }

    assert _is_benign_asyncio_connection_reset(context) is False


def test_unrelated_callback_exception_is_reported() -> None:
    context: dict[str, object] = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": RuntimeError("boom"),
        "handle": _ConnectionLostHandle(),
    }

    assert _is_benign_asyncio_connection_reset(context) is False

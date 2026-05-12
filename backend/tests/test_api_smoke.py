from __future__ import annotations

from src.api.app import create_app
from src.api.http.http_api import get_health_status


class _HealthySession:
    def execute(self, statement) -> None:
        self.statement = statement


class _FailingSession:
    def execute(self, statement) -> None:
        raise RuntimeError("database unavailable")


def test_create_app_registers_api_routes() -> None:
    application = create_app()
    route_paths = {route.path for route in application.router.routes}

    assert "/api/health" in route_paths
    assert "/api/status" in route_paths
    assert "/ws" in route_paths


def test_health_status_reports_ok_when_database_is_reachable() -> None:
    payload = get_health_status(database_session=_HealthySession())

    assert payload.status == "ok"
    assert payload.components.database.ok is True


def test_health_status_reports_degraded_when_database_is_unreachable() -> None:
    payload = get_health_status(database_session=_FailingSession())

    assert payload.status == "degraded"
    assert payload.components.database.ok is False

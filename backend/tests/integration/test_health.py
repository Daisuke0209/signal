from fastapi.routing import APIRoute

from signal_api.database import SessionLocal
from signal_api.main import app, health


def test_health_reports_database_connection() -> None:
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/health"
    ]
    assert len(routes) == 1
    methods = routes[0].methods
    assert methods is not None
    assert "GET" in methods

    with SessionLocal() as db:
        response = health(db)

    assert response.status == "ok"
    assert response.database

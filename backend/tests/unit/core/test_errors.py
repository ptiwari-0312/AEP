from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aep.core.errors import (
    AEPError,
    ConflictError,
    NotFoundError,
    ValidationFailedError,
    register_exception_handlers,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    def _raise_not_found():
        raise NotFoundError("project not found", detail="No project with that id exists.")

    @app.get("/conflict")
    def _raise_conflict():
        raise ConflictError("illegal transition")

    @app.get("/validation")
    def _raise_validation():
        raise ValidationFailedError(
            "validation failed", errors=[{"field": "slug", "message": "must be lowercase"}]
        )

    return app


def test_not_found_maps_to_404_problem_details() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.get("/not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["title"] == "NotFoundError"
    assert body["status"] == 404
    assert body["detail"] == "No project with that id exists."
    assert body["type"] == "https://aep.dev/errors/NotFoundError"
    assert body["instance"] == "/not-found"


def test_conflict_maps_to_409() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.get("/conflict")

    assert response.status_code == 409


def test_validation_failed_includes_errors_array() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.get("/validation")

    assert response.status_code == 422
    body = response.json()
    assert body["errors"] == [{"field": "slug", "message": "must be lowercase"}]


def test_unmapped_aep_error_defaults_to_500() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def _raise_generic():
        raise AEPError("something went wrong")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500

from fastapi.testclient import TestClient

from aiseoonline_api.main import create_app


def test_health_is_live_without_external_services() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "aiseoonline-api",
        "version": "0.1.0",
    }


def test_openapi_documents_health_response() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/openapi.json")
        docs = client.get("/api/docs")
    assert response.status_code == 200
    assert response.json()["paths"]["/api/v1/health"]["get"]["responses"]["200"]
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text


def test_unknown_endpoint_returns_404() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/not-a-route").status_code == 404

"""Tests for GET /health."""


def test_health_check_returns_200_and_healthy_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

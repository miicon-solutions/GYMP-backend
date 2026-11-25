from django.conf import settings


def test_landing_shows_version(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.content.decode()
    assert settings.APP_VERSION in body
    assert settings.APP_ENV in body


def test_landing_shows_built_at(client, settings):
    settings.APP_BUILT_AT = "2026-11-25T12:00:00Z"
    response = client.get("/")
    assert response.status_code == 200
    assert "Built 2026-11-25T12:00:00Z" in response.content.decode()

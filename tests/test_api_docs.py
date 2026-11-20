import yaml
from django.test import Client

from core.api_docs import FEATURE_NAMES, feature_tag_for_path, filter_schema_by_feature


def test_feature_tag_for_path():
    assert feature_tag_for_path("/api/v1/auth/otp/send/") == "auth"
    assert feature_tag_for_path("/api/v1/admin/members/") == "admin-members"
    assert feature_tag_for_path("/api/v1/admin/revenue/") == "reports"
    assert feature_tag_for_path("/api/v1/workouts/sessions/") == "fitness"


def test_docs_and_feature_schema_endpoints():
    client = Client()
    assert client.get("/docs/").status_code == 200
    assert client.get("/docs/v1/").status_code == 200
    assert client.get("/docs/v1/reference/").status_code == 200
    assert client.get("/docs/features/").status_code == 200
    assert client.get("/docs/features/?format=json").status_code == 200
    assert client.get("/docs/features/auth/").status_code == 200
    assert client.get("/docs/features/auth/?format=md").status_code == 200

    full = client.get("/openapi/v1.yaml")
    assert full.status_code == 200
    schema = yaml.safe_load(full.content)
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    assert {tag["name"] for tag in schema["tags"]} == FEATURE_NAMES

    full_json = client.get("/openapi/v1.json")
    assert full_json.status_code == 200
    assert full_json["Content-Type"].startswith("application/json")
    assert full_json.json()["info"]["title"]

    auth = client.get("/openapi/v1/auth.yaml")
    assert auth.status_code == 200
    auth_schema = yaml.safe_load(auth.content)
    assert auth_schema["paths"]
    for methods in auth_schema["paths"].values():
        for method, operation in methods.items():
            if method.startswith("x-"):
                continue
            assert operation["tags"] == ["auth"]

    filtered = filter_schema_by_feature(schema, "payments")
    assert filtered["paths"]
    assert filtered["tags"][0]["name"] == "payments"

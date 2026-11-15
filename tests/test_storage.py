import json
import os
import subprocess
import sys
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from storages.backends.s3 import S3Storage

from members import services
from members.models import MemberProfile


def configured_settings(**overrides):
    # Ignore any developer .env file, including real credentials and provider settings.
    script = """
import json
from unittest.mock import patch
with patch('environ.Env.read_env'):
    from config import settings as s
print(json.dumps({'storage': s.STORAGES['default'], 'database_host': s.DATABASES['default']['HOST']}))
"""
    return subprocess.run(
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "APP_ENV": "local",
            "DJANGO_SECRET_KEY": "local-test-django-secret-that-is-long-enough",
            "JWT_SECRET": "local-test-jwt-secret-that-is-long-enough",
            "DATABASE_URL": "postgres://user:password@external-postgres:5432/gyma",
            "MEDIA_STORAGE": "s3",
            "AWS_STORAGE_BUCKET_NAME": "gyma-test-media",
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            "AWS_SESSION_TOKEN": "",
            "AWS_S3_ENDPOINT_URL": "http://minio.example.test:9000",
            "AWS_S3_REGION_NAME": "us-east-1",
            "AWS_S3_ADDRESSING_STYLE": "path",
            "AWS_LOCATION": "media",
            "AWS_QUERYSTRING_EXPIRE": "600",
            **overrides,
        },
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("provider", ["minio", "aws"])
def test_configured_s3_generates_private_signed_urls_without_network(provider):
    overrides = {}
    if provider == "aws":
        overrides = {
            "AWS_S3_ENDPOINT_URL": "",
            "AWS_S3_REGION_NAME": "eu-west-1",
            "AWS_S3_ADDRESSING_STYLE": "virtual",
            "AWS_SESSION_TOKEN": "temporary-session-token",
        }
    result = configured_settings(**overrides)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["database_host"] == "external-postgres"
    storage = S3Storage(**config["storage"]["OPTIONS"])
    assert storage.default_acl is None
    assert storage.file_overwrite is False
    assert storage.custom_domain is None
    url = urlsplit(storage.url("photo.png"))
    query = parse_qs(url.query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["600"]
    assert query["X-Amz-Signature"]
    if provider == "minio":
        assert url.netloc == "minio.example.test:9000"
        assert url.path == "/gyma-test-media/media/photo.png"
    else:
        assert url.scheme == "https"
        assert url.netloc == "gyma-test-media.s3.eu-west-1.amazonaws.com"
        assert url.path == "/media/photo.png"
        assert "/eu-west-1/s3/aws4_request" in query["X-Amz-Credential"][0]
        assert query["X-Amz-Security-Token"] == ["temporary-session-token"]


def test_s3_credentials_can_use_aws_default_chain():
    result = configured_settings(AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="")
    assert result.returncode == 0, result.stderr
    options = json.loads(result.stdout)["storage"]["OPTIONS"]
    assert options["access_key"] is None
    assert options["secret_key"] is None


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"MEDIA_STORAGE": "unknown"}, "MEDIA_STORAGE must be"),
        ({"AWS_STORAGE_BUCKET_NAME": ""}, "AWS_STORAGE_BUCKET_NAME is required"),
        ({"AWS_S3_ENDPOINT_URL": "minio:9000"}, "AWS_S3_ENDPOINT_URL must be"),
        ({"AWS_S3_ADDRESSING_STYLE": "unknown"}, "AWS_S3_ADDRESSING_STYLE must be"),
        ({"AWS_QUERYSTRING_EXPIRE": "0"}, "AWS_QUERYSTRING_EXPIRE must be"),
        ({"AWS_QUERYSTRING_EXPIRE": "604801"}, "AWS_QUERYSTRING_EXPIRE must be"),
    ],
)
def test_invalid_storage_settings_fail_without_disk_fallback(overrides, message):
    result = configured_settings(**overrides)
    assert result.returncode != 0
    assert message in result.stderr


def test_filesystem_checks_need_no_bucket_or_credentials():
    result = configured_settings(
        MEDIA_STORAGE="filesystem",
        AWS_STORAGE_BUCKET_NAME="",
        AWS_ACCESS_KEY_ID="",
        AWS_SECRET_ACCESS_KEY="",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["storage"]["BACKEND"].endswith("FileSystemStorage")


class RemoteStorage(Storage):
    """An object store deliberately lacking local paths and file downloads."""

    def __init__(self):
        self.objects = {}
        self.deleted = []

    def _save(self, name, content):
        self.objects[name] = content.read()
        return name

    def exists(self, name):
        return name in self.objects

    def delete(self, name):
        self.deleted.append(name)
        self.objects.pop(name, None)

    def url(self, name):
        return f"https://objects.example.test/media/{name}?X-Amz-Signature=test"


@pytest.fixture
def remote_storage(monkeypatch, settings):
    storage = RemoteStorage()
    monkeypatch.setattr(MemberProfile._meta.get_field("photo"), "storage", storage)
    settings.MEDIA_STORAGE = "s3"
    return storage


def photo_file():
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(buffer, format="PNG")
    return SimpleUploadedFile("upload.png", buffer.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_remote_photo_upload_replace_delete(
    client, member, remote_storage, django_capture_on_commit_callbacks
):
    client.force_authenticate(member)
    endpoint = "/api/v1/member/profile/photo/"
    first = client.post(endpoint, {"photo": photo_file()}, format="multipart")
    assert first.status_code == 200
    old_name = MemberProfile.objects.get(user=member).photo.name
    assert first.data["photo_url"] == remote_storage.url(old_name)
    assert client.get("/api/v1/member/profile/").data["photo_url"] == first.data["photo_url"]
    with django_capture_on_commit_callbacks(execute=True):
        second = client.post(endpoint, {"photo": photo_file()}, format="multipart")
        assert old_name in remote_storage.objects
        assert not remote_storage.deleted
    assert second.status_code == 200
    new_name = MemberProfile.objects.get(user=member).photo.name
    assert new_name != old_name
    assert second.data["photo_url"] == remote_storage.url(new_name)
    assert set(remote_storage.objects) == {new_name}
    assert remote_storage.deleted == [old_name]
    with django_capture_on_commit_callbacks(execute=True):
        assert client.delete(endpoint).status_code == 204
        assert new_name in remote_storage.objects
    assert not remote_storage.objects
    assert remote_storage.deleted == [old_name, new_name]
    assert client.get("/api/v1/member/profile/").data["photo_url"] is None


@pytest.mark.django_db
def test_failed_photo_database_update_cleans_new_object(member, remote_storage, monkeypatch):
    services.upload_photo(member, photo_file())
    old_name = MemberProfile.objects.get(user=member).photo.name

    def failed_save(*args, **kwargs):
        raise RuntimeError("Database write failed")

    monkeypatch.setattr(MemberProfile, "save", failed_save)
    with pytest.raises(RuntimeError, match="Database write failed"):
        services.upload_photo(member, photo_file())
    assert MemberProfile.objects.get(user=member).photo.name == old_name
    assert set(remote_storage.objects) == {old_name}
    assert len(remote_storage.deleted) == 1
    assert remote_storage.deleted[0] != old_name


@pytest.mark.django_db
def test_storage_outage_leaves_existing_photo_and_disk_untouched(
    member, remote_storage, monkeypatch, tmp_path
):
    services.upload_photo(member, photo_file())
    old_name = MemberProfile.objects.get(user=member).photo.name

    def failed_save(*args, **kwargs):
        raise OSError("Object storage unavailable")

    monkeypatch.setattr(remote_storage, "_save", failed_save)
    with pytest.raises(OSError, match="Object storage unavailable"):
        services.upload_photo(member, photo_file())
    assert MemberProfile.objects.get(user=member).photo.name == old_name
    assert set(remote_storage.objects) == {old_name}
    assert not remote_storage.deleted
    assert not list(tmp_path.glob("*.png"))


def test_s3_mode_never_exposes_legacy_local_photos(client, settings):
    filename = "a" * 32 + ".png"
    (settings.MEDIA_ROOT / filename).write_bytes(b"private local photo")
    settings.MEDIA_STORAGE = "s3"
    assert client.get("/media/member-photos/" + filename).status_code == 404

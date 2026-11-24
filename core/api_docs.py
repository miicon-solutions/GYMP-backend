"""Feature-wise, versioned OpenAPI docs for humans and AI agents."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import yaml
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

FEATURE_TAGS: list[dict[str, str]] = [
    {"name": "auth", "description": "OTP, Google, refresh, logout, and staff MFA."},
    {"name": "member", "description": "Member profile, photo, dashboard, and gym status."},
    {"name": "admin-members", "description": "Staff member CRUD, phone link, fingerprint, cash."},
    {"name": "plans", "description": "Catalog plans, offers, and public plan listing."},
    {"name": "payments", "description": "SSLCommerz sessions, IPN, cash requests, receipts."},
    {"name": "attendance", "description": "Member calendar and device/internal check-in."},
    {"name": "device", "description": "Device status, controllers, and biometric vault."},
    {"name": "staff", "description": "Staff CRUD, permissions catalog, and MFA enroll."},
    {"name": "operations", "description": "Costs, gym hours, holidays, and activity."},
    {"name": "reports", "description": "Revenue and reporting."},
    {"name": "fitness", "description": "Workouts, schedules, nutrition, journal, and feed."},
    {"name": "music", "description": "Music queue and catalog."},
    {
        "name": "notifications",
        "description": "Member in-app feed, FCM devices, and admin announcements.",
    },
    {"name": "public", "description": "Welcome and other unauthenticated public APIs."},
]

FEATURE_NAMES = frozenset(tag["name"] for tag in FEATURE_TAGS)

# Longest-prefix match against the path after /api/v1/ (or /api/).
_PATH_TAG_RULES: list[tuple[str, str]] = [
    ("auth/", "auth"),
    ("member/attendance", "attendance"),
    ("member/payments", "payments"),
    ("member/plans", "plans"),
    ("member/notifications", "notifications"),
    ("member/devices", "notifications"),
    ("member/", "member"),
    ("admin/notifications", "notifications"),
    ("admin/members", "admin-members"),
    ("admin/cash-requests", "admin-members"),
    ("admin/device", "device"),
    ("admin/staff", "staff"),
    ("admin/plans", "plans"),
    ("admin/costs", "operations"),
    ("admin/activity", "operations"),
    ("admin/gym-hours", "operations"),
    ("admin/revenue", "reports"),
    ("admin/reports", "reports"),
    ("internal/attendance", "attendance"),
    ("internal/biometrics", "device"),
    ("internal/bridge", "device"),
    ("webhooks/", "payments"),
    ("public/plans", "plans"),
    ("public/", "public"),
    ("welcome/", "public"),
    ("workouts/", "fitness"),
    ("schedules/", "fitness"),
    ("nutrition/", "fitness"),
    ("journal/", "fitness"),
    ("feed/", "fitness"),
    ("users/", "fitness"),
    ("music/", "music"),
]

_COMPONENT_REF = re.compile(r"#/components/([^/]+)/([^\"'\s}]+)")


def feature_tag_for_path(path: str) -> str:
    """Map an OpenAPI path to a feature tag."""
    normalized = path.split("?", 1)[0]
    for prefix in ("/api/v1/", "/api/"):
        if normalized.startswith(prefix):
            rest = normalized[len(prefix) :]
            break
    else:
        rest = normalized.lstrip("/")
    for rule_prefix, tag in _PATH_TAG_RULES:
        if rest.startswith(rule_prefix):
            return tag
    return "public"


def preprocess_versioned_paths(endpoints):
    """Publish only /api/v1/ routes so /api/ duplicates do not clutter the schema."""
    filtered = []
    for path, path_regex, method, callback in endpoints:
        if path.startswith("/api/") and not path.startswith("/api/v1/"):
            continue
        filtered.append((path, path_regex, method, callback))
    return filtered


def postprocess_feature_tags(result, generator, request, public):
    """Assign feature tags from path (source of truth for the docs menu)."""
    del generator, request, public
    paths = result.get("paths") or {}
    for path, methods in paths.items():
        derived = feature_tag_for_path(path)
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            operation["tags"] = [derived]
    result["tags"] = FEATURE_TAGS
    info = result.setdefault("info", {})
    info.setdefault("title", "GYMP API")
    info["version"] = getattr(settings, "API_DOC_VERSION_LABEL", "1.0.0")
    info["description"] = (
        "GYMP membership platform API. Use feature packs at `/docs/features/{feature}/` "
        "or filtered OpenAPI at `/openapi/v1/{feature}.yaml` to wire one feature at a time."
    )
    return result


def _collect_refs(node, refs: set[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            match = _COMPONENT_REF.match(ref)
            if match:
                refs.add((match.group(1), match.group(2)))
        for value in node.values():
            _collect_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, refs)


def filter_schema_by_feature(schema: dict, feature: str) -> dict:
    """Return a copy of the schema containing only operations for one feature tag."""
    if feature not in FEATURE_NAMES:
        raise KeyError(feature)
    filtered = copy.deepcopy(schema)
    paths: dict = {}
    for path, methods in (schema.get("paths") or {}).items():
        kept_methods = {}
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or []
            if feature in tags or feature_tag_for_path(path) == feature:
                kept_methods[method] = copy.deepcopy(operation)
                kept_methods[method]["tags"] = [feature]
        if kept_methods:
            paths[path] = kept_methods
    filtered["paths"] = paths
    filtered["tags"] = [tag for tag in FEATURE_TAGS if tag["name"] == feature]

    components = copy.deepcopy(schema.get("components") or {})
    used: set[tuple[str, str]] = set()
    _collect_refs(paths, used)
    # Expand transitive refs until stable.
    changed = True
    while changed:
        changed = False
        snapshot = set(used)
        for section, name in snapshot:
            node = (components.get(section) or {}).get(name)
            if node is not None:
                before = len(used)
                _collect_refs(node, used)
                if len(used) > before:
                    changed = True
    trimmed = {}
    for section, items in components.items():
        if not isinstance(items, dict):
            trimmed[section] = items
            continue
        kept = {name: value for name, value in items.items() if (section, name) in used}
        if kept:
            trimmed[section] = kept
    if trimmed:
        filtered["components"] = trimmed
    elif "components" in filtered:
        del filtered["components"]

    info = filtered.setdefault("info", {})
    title = next((t["description"] for t in FEATURE_TAGS if t["name"] == feature), feature)
    info["title"] = f"GYMP API — {feature}"
    info["description"] = (
        f"Feature pack `{feature}`: {title} "
        f"Full schema: `/openapi/v1.yaml`. Narrative: `/docs/features/{feature}/`."
    )
    return filtered


def docs_root() -> Path:
    return Path(settings.BASE_DIR) / "docs"


def openapi_v1_path() -> Path:
    return docs_root() / "openapi" / "v1.yaml"


def features_dir() -> Path:
    return docs_root() / "features"


def features_index_path() -> Path:
    return features_dir() / "index.json"


def load_committed_schema() -> dict | None:
    path = openapi_v1_path()
    legacy = docs_root() / "openapi.yaml"
    for candidate in (path, legacy):
        if candidate.is_file():
            with candidate.open(encoding="utf-8") as handle:
                return yaml.safe_load(handle)
    return None


def generate_live_schema(request=None) -> dict:
    from drf_spectacular.generators import SchemaGenerator

    generator = SchemaGenerator(urlconf=None)
    return generator.get_schema(request=request, public=True) or {}


def resolve_schema(request=None) -> dict:
    """Prefer live spectacular schema; fall back to committed YAML."""
    try:
        schema = generate_live_schema(request=request)
        if schema.get("paths"):
            return schema
    except Exception:
        pass
    committed = load_committed_schema()
    if committed:
        return committed
    return {"openapi": "3.0.3", "info": {"title": "GYMP API", "version": "1.0.0"}, "paths": {}}


def build_features_index(schema: dict | None = None) -> dict:
    schema = schema or resolve_schema()
    features: dict[str, dict] = {}
    for tag in FEATURE_TAGS:
        name = tag["name"]
        operations: list[str] = []
        for path, methods in (schema.get("paths") or {}).items():
            for method, operation in methods.items():
                if method.startswith("x-") or not isinstance(operation, dict):
                    continue
                tags = operation.get("tags") or []
                if name in tags or feature_tag_for_path(path) == name:
                    op_id = operation.get("operationId")
                    if op_id:
                        operations.append(op_id)
        operations = sorted(set(operations))
        features[name] = {
            "title": name.replace("-", " ").title(),
            "description": tag["description"],
            "openapi": f"/openapi/v1/{name}.yaml",
            "doc": f"/docs/features/{name}/",
            "operations": operations,
        }
    return {
        "version": getattr(settings, "DEFAULT_API_DOC_VERSION", "v1"),
        "base_url": "/api/v1/",
        "schema": "/openapi/v1.yaml",
        "docs": "/docs/v1/",
        "features": features,
    }


def write_features_index(schema: dict | None = None) -> Path:
    index = build_features_index(schema)
    path = features_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return path


def _wants_json(request) -> bool:
    path = request.path
    if path.endswith(".json") or request.GET.get("format") == "json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "application/yaml" not in accept


def _schema_response(data: dict, *, as_json: bool) -> HttpResponse:
    if as_json:
        return HttpResponse(
            json.dumps(data, indent=2, default=str) + "\n",
            content_type="application/json; charset=utf-8",
        )
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return HttpResponse(body, content_type="application/yaml; charset=utf-8")


def _validate_version(version: str) -> str:
    versions = getattr(settings, "API_DOC_VERSIONS", ("v1",))
    if version not in versions:
        raise Http404(f"Unknown API docs version: {version}")
    return version


@extend_schema(exclude=True)
class VersionedSchemaView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, version="v1"):
        _validate_version(version)
        return _schema_response(resolve_schema(request=request), as_json=_wants_json(request))


@extend_schema(exclude=True)
class FeatureSchemaView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, version="v1", feature="auth"):
        _validate_version(version)
        if feature not in FEATURE_NAMES:
            raise Http404(f"Unknown feature: {feature}")
        return _schema_response(
            filter_schema_by_feature(resolve_schema(request=request), feature),
            as_json=_wants_json(request),
        )


class DocsUIView(View):
    """Docs chrome with in-page Scalar (no iframe — clipboard/Copy as Markdown works)."""

    def get(self, request, version=None):
        default = getattr(settings, "DEFAULT_API_DOC_VERSION", "v1")
        version = _validate_version(version or default)
        versions = list(getattr(settings, "API_DOC_VERSIONS", ("v1",)))
        return render(
            request,
            "api_docs.html",
            {
                "version": version,
                "versions": versions,
                "schema_yaml_url": f"/openapi/{version}.yaml",
                "schema_json_url": f"/openapi/{version}.json",
                "features": FEATURE_TAGS,
                "features_index_url": "/docs/features/",
                "swagger_url": "/docs/swagger/",
            },
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class DocsScalarFrameView(View):
    """Fullscreen Scalar host (also embeddable; primary docs mount Scalar in-page)."""

    def get(self, request, version="v1"):
        version = _validate_version(version)
        return render(
            request,
            "api_docs_scalar_frame.html",
            {
                "version": version,
                "schema_url": f"/openapi/{version}.json",
            },
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class DocsSwaggerFrameView(SpectacularSwaggerView):
    """Swagger UI embeddable in the docs chrome iframe."""

    url_name = "schema-json"


class FeaturesIndexView(View):
    def get(self, request):
        accept = request.headers.get("Accept", "")
        index_path = features_index_path()
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            index = build_features_index(resolve_schema(request=request))
        if "application/json" in accept or request.GET.get("format") == "json":
            return JsonResponse(index)
        return render(
            request,
            "api_features_index.html",
            {"index": index, "features": FEATURE_TAGS},
        )


class FeaturePackView(View):
    def get(self, request, feature):
        if feature not in FEATURE_NAMES:
            raise Http404(f"Unknown feature: {feature}")
        md_path = features_dir() / f"{feature}.md"
        raw = request.GET.get("format") == "md" or "text/markdown" in request.headers.get(
            "Accept", ""
        )
        if md_path.is_file():
            content = md_path.read_text(encoding="utf-8")
        else:
            tag = next(t for t in FEATURE_TAGS if t["name"] == feature)
            content = (
                f"# {feature}\n\n{tag['description']}\n\n"
                f"- OpenAPI: `/openapi/v1/{feature}.yaml`\n"
                f"- Full schema: `/openapi/v1.yaml`\n"
            )
        if raw:
            return HttpResponse(content, content_type="text/markdown; charset=utf-8")
        return render(
            request,
            "api_feature_pack.html",
            {
                "feature": feature,
                "content": content,
                "openapi_url": f"/openapi/v1/{feature}.yaml",
                "schema_url": "/openapi/v1.yaml",
                "docs_url": "/docs/v1/",
            },
        )

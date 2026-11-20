from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api_docs import FEATURE_NAMES, feature_tag_for_path


class Empty(serializers.Serializer):
    pass


class ObjectResponse(serializers.Serializer):
    """Operation-specific resource; see the migration reference and examples."""


def _default_tags(name: str, tags: list[str] | None) -> list[str]:
    if tags:
        unknown = [tag for tag in tags if tag not in FEATURE_NAMES]
        if unknown:
            raise ValueError(f"Unknown API feature tags: {unknown}")
        return list(tags)
    # Hint only; path-based postprocessing in core.api_docs overwrites for the schema.
    head = name.split("_", 1)[0]
    if head in FEATURE_NAMES:
        return [head]
    return [head]


def endpoint(
    name,
    handler,
    *,
    method="post",
    request=Empty,
    response=ObjectResponse,
    permission=AllowAny,
    status=200,
    parameters=None,
    parsers=None,
    authentication=None,
    throttle_public=True,
    tags=None,
    examples=None,
):
    """Declare a small service endpoint with explicit validation and OpenAPI metadata.

    Prefer an explicit ``tags`` list from the feature taxonomy in ``core.api_docs``.
    Path-based postprocessing still normalizes tags when omitted.
    """

    def execute(self, http_request, **kwargs):
        from accounts.services import throttle

        if throttle_public and permission is AllowAny and method != "get":
            from core.network import client_ip

            throttle("request:" + name + ":" + client_ip(http_request), 60, 60)
        serializer = request(
            data=http_request.query_params if method == "get" else http_request.data
        )
        serializer.is_valid(raise_exception=True)
        result = handler(http_request, serializer.validated_data, **kwargs)
        return (
            result
            if isinstance(result, Response) or hasattr(result, "status_code")
            else Response(result, status=status)
        )

    execute.__name__ = method
    schema_kwargs = {
        "operation_id": name,
        "request": request if method != "get" else None,
        "responses": response if isinstance(response, dict) else {status: response},
        "parameters": parameters or [],
        "tags": _default_tags(name, tags),
    }
    if examples:
        schema_kwargs["examples"] = examples
    attrs = {
        "permission_classes": [permission],
        "serializer_class": request,
        method: extend_schema(**schema_kwargs)(execute),
        "__module__": __name__,
    }
    if parsers is not None:
        attrs["parser_classes"] = parsers
    if authentication is not None:
        attrs["authentication_classes"] = authentication
    return type(name, (APIView,), attrs).as_view()


def query_parameters(*names):
    return [OpenApiParameter(name, str, OpenApiParameter.QUERY) for name in names]


def tag_for_view_path(path: str) -> list[str]:
    """Helper for ViewSet ``extend_schema(tags=…)`` calls."""
    return [feature_tag_for_path(path)]

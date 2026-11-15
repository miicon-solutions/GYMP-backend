from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class Empty(serializers.Serializer):
    pass


class ObjectResponse(serializers.Serializer):
    """Operation-specific resource; see the migration reference and examples."""


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
):
    """Declare a small service endpoint with explicit validation and OpenAPI metadata."""

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
    attrs = {
        "permission_classes": [permission],
        "serializer_class": request,
        method: extend_schema(
            operation_id=name,
            request=request if method != "get" else None,
            responses=response if isinstance(response, dict) else {status: response},
            parameters=parameters or [],
            tags=[name.split("_")[0]],
        )(execute),
        "__module__": __name__,
    }
    if parsers is not None:
        attrs["parser_classes"] = parsers
    if authentication is not None:
        attrs["authentication_classes"] = authentication
    return type(name, (APIView,), attrs).as_view()


def query_parameters(*names):
    return [OpenApiParameter(name, str, OpenApiParameter.QUERY) for name in names]

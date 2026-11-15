import logging
import re
import time
import uuid

SENSITIVE = re.compile(
    r"token|password|secret|api.?key|authorization|cookie|totp|security_code|otp_code", re.I
)


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[redacted]" if SENSITIVE.search(str(k)) else redact(v) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class RedactFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, dict):
            record.msg = redact(record.msg)
        if isinstance(record.args, dict):
            record.args = redact(record.args)
        for key in list(record.__dict__):
            if SENSITIVE.search(key):
                record.__dict__[key] = "[redacted]"
        return True


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        candidate = request.headers.get("X-Request-ID", "")
        request.request_id = (
            candidate if re.fullmatch(r"[\w-]{1,80}", candidate) else str(uuid.uuid4())
        )
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        # Do not log query strings, headers, bodies, provider exceptions, or credentials.
        logging.getLogger("gyma.http").info(
            {
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "request_id": request.request_id,
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        )
        return response


class UploadLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import JsonResponse

        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return JsonResponse({"detail": "Invalid request length."}, status=400)
        if length > 6 * 1024 * 1024:
            return JsonResponse({"detail": "Request must be under 6 MB."}, status=413)
        return self.get_response(request)


class TrustedProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        if request.META.get("REMOTE_ADDR") in settings.TRUSTED_PROXY_IPS:
            scheme = request.META.get("HTTP_X_FORWARDED_PROTO")
            if scheme in {"http", "https"}:
                request.META["wsgi.url_scheme"] = scheme
        return self.get_response(request)

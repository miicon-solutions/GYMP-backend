import re
from urllib.parse import urlencode

from django.conf import settings
from django.db import connection, transaction
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods


@require_GET
def landing(request):
    return render(request, "index.html")


@require_GET
def health(request):
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute("SET LOCAL statement_timeout = '2s'")
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ok", "database": {"status": "ok"}})
    except Exception:
        return JsonResponse({"status": "degraded", "database": {"status": "unhealthy"}}, status=503)


@require_GET
def live(request):
    return JsonResponse({"status": "ok"})


@require_GET
def photo(request, filename):
    if settings.MEDIA_STORAGE != "filesystem" or not re.fullmatch(
        r"[a-f0-9]{32}\.(jpg|png|webp)", filename
    ):
        raise Http404
    path = settings.MEDIA_ROOT / filename
    try:
        return FileResponse(
            path.open("rb"),
            content_type={"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[
                path.suffix[1:]
            ],
        )
    except FileNotFoundError as exc:
        raise Http404 from exc


@csrf_exempt
@require_http_methods(["GET", "POST"])
def payment_return(request, outcome):
    if outcome not in {"success", "fail", "cancel"}:
        raise Http404
    tran_id = (request.GET.get("tran_id") or request.POST.get("tran_id", ""))[:30]
    if settings.WEB_APP_BASE_URL:
        query = urlencode({"tran_id": tran_id})
        response = HttpResponseRedirect(
            f"{settings.WEB_APP_BASE_URL}/payments/return/{outcome}?{query}"
        )
        response["Cache-Control"] = "no-store"
        return response
    return render(
        request,
        "payment_return.html",
        {"outcome": outcome, "tran_id": tran_id},
    )


def not_found(request, exception=None):
    return JsonResponse({"detail": "Not found."}, status=404)


def server_error(request):
    return JsonResponse({"detail": "Something went wrong. Please try again."}, status=500)

import re

from django.conf import settings
from django.db import connection, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def landing(request):
    return render(request, "index.html")


@require_GET
def legal(request, page):
    return render(request, page + ".html")


@require_GET
def health(request):
    try:
        with transaction.atomic(), connection.cursor() as cursor:
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
    if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", filename):
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


@require_GET
def payment_return(request, outcome):
    if outcome not in {"success", "fail", "cancel"}:
        raise Http404
    return render(
        request,
        "payment_return.html",
        {"outcome": outcome, "tran_id": request.GET.get("tran_id", "")[:30]},
    )


def not_found(request, exception=None):
    return JsonResponse({"detail": "Not found."}, status=404)


def server_error(request):
    return JsonResponse({"detail": "Something went wrong. Please try again."}, status=500)

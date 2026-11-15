from django.contrib.admin import AdminSite
from django.http import HttpResponse
from rest_framework.exceptions import Throttled

from accounts.services import throttle
from core.network import client_ip


class OperatorAdminSite(AdminSite):
    site_header = "GYMA operations"
    site_title = "GYMA"

    def login(self, request, extra_context=None):
        if request.method == "POST":
            try:
                throttle("operator-ip:" + client_ip(request), 30, 60)
                throttle("operator-user:" + request.POST.get("username", "").strip(), 10, 60)
            except Throttled as exc:
                response = HttpResponse(
                    "Too many attempts. Try again shortly.", status=429, content_type="text/plain"
                )
                response["Retry-After"] = str(exc.wait)
                return response
        return super().login(request, extra_context)

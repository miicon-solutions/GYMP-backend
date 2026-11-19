from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.urls import path, reverse

from accounts.models import StaffProfile, User
from accounts.services import begin_mfa
from core.admin import OperatorModelAdmin


@admin.register(User)
class UserAdmin(OperatorModelAdmin):
    # Password hash and firebase_uid stay off the form; set passwords via bootstrap/seed only.
    # Deleting a user cascades staff/member profile, payments, sessions, and check-ins.
    fields = [
        "id",
        "phone_e164",
        "full_name",
        "email",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
        "updated_at",
    ]
    list_display = ["phone_e164", "full_name", "role", "is_active", "is_staff"]
    list_filter = ["role", "is_active", "is_staff"]
    search_fields = ["phone_e164", "full_name", "email"]
    readonly_fields = ("id", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.pk == request.user.pk:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(StaffProfile)
class StaffAdmin(OperatorModelAdmin):
    change_form_template = "admin/accounts/staffprofile/change_form.html"
    # TOTP secret, setup token hash, and last step stay off the form.
    fields = ["id", "user", "short_id", "mfa_enrolled_at", "created_at", "updated_at"]
    list_display = ["short_id", "user", "mfa_enrolled_at"]
    search_fields = ["short_id", "user__full_name", "user__phone_e164"]
    readonly_fields = ("id", "created_at", "updated_at", "mfa_enrolled_at")

    def get_urls(self):
        return [
            path(
                "<path:object_id>/mfa-enroll/",
                self.admin_site.admin_view(self.mfa_enroll_view),
                name="accounts_staffprofile_mfa_enroll",
            ),
        ] + super().get_urls()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        profile = self.get_object(request, unquote(object_id))
        extra_context = {
            **(extra_context or {}),
            "show_mfa_enrollment": bool(
                request.user.is_superuser
                and profile
                and profile.user.is_active
                and profile.user.role == "admin"
            ),
        }
        return super().change_view(request, object_id, form_url, extra_context)

    def mfa_enroll_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        profile = self.get_object(request, unquote(object_id))
        if not profile:
            raise Http404("Staff not found.")
        setup = None
        with transaction.atomic():
            # Match the API's user lock so enrollment and confirmation cannot race.
            user = User.objects.select_for_update().get(pk=profile.user_id)
            if not user.is_active or user.role != "admin":
                raise Http404("Active staff not found.")
            if request.method == "POST":
                setup = begin_mfa(user)
                self.log_change(request, profile, "Generated a one-time MFA setup token.")
        response = TemplateResponse(
            request,
            "admin/accounts/staffprofile/mfa_enroll.html",
            {
                **self.admin_site.each_context(request),
                "title": "Set up / reset MFA",
                "opts": self.model._meta,
                "original": profile,
                "staff_user": user,
                "setup": setup,
                "change_url": reverse(
                    "admin:accounts_staffprofile_change",
                    args=[profile.pk],
                    current_app=self.admin_site.name,
                ),
            },
        )
        # Native form POSTs need the real same-origin Origin/Referer for CSRF checks.
        response["Referrer-Policy"] = "same-origin"
        return response

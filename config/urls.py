from django.conf import settings
from django.contrib import admin
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import include, path
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import inline_serializer
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework import serializers
from rest_framework.permissions import AllowAny

from accounts import serializers as auth_s
from accounts import services as auth
from accounts.staff_permissions import catalog_payload
from attendance.authentication import DeviceAuthentication
from attendance.serializers import (
    CheckInInput,
    CheckInOutput,
    MemberSessionAdjustInput,
    MonthInput,
    MonthOutput,
)
from attendance.services import (
    member_adjust_session,
    month_attendance,
    record_checkin,
    record_checkout,
)
from biometrics import services as bio
from biometrics.serializers import (
    DeviceStatusOutput,
    EnrollInteractiveInput,
    EnrollInteractiveOutput,
    MemberTemplatesOutput,
    StaffEnrollInteractiveOutput,
    StaffTemplatesOutput,
    VaultBulkPushInput,
    VaultBulkPushOutput,
    VaultMembersOutput,
    VaultSyncOutput,
)
from core import public
from core.api import MemberOnly, StaffPermission, SuperOnly
from core.endpoints import endpoint, query_parameters
from members import services as member
from members.serializers import (
    AdminMemberOutput,
    DashboardOutput,
    FingerprintInput,
    ProfileInput,
    ProfileOutput,
    RecoveryOutput,
)
from members.views import AdminMemberDetail, AdminMemberList, PhotoView, ProfileView
from operations import services as ops
from operations.serializers import (
    CostSerializer,
    DeviceControllerRemovedOutput,
    GymHoursOutput,
    GymStatusOutput,
    StaffSerializer,
    WeekInput,
)
from operations.views import (
    ActivityList,
    CostDetail,
    CostList,
    DeviceControllersList,
    HolidayDetail,
    HolidayList,
    StaffDetail,
    StaffList,
    staff_by_id,
)
from payments import services as payment
from payments.serializers import (
    CashPaymentRequestSerializer,
    CashPreviewOutput,
    CashRequestStatusFilter,
    IPNInput,
    MemberCashPaymentRequestSerializer,
    PaymentSerializer,
    PlanInput,
    SessionInput,
    SessionSerializer,
)
from payments.views import PaymentDetail, PaymentList, receipt
from plans.views import (
    MemberPlanDetail,
    MemberPlanList,
    OfferDetail,
    OfferList,
    PlanDetail,
    PlanList,
    PublicPlanList,
)
from reporting.serializers import RevenueOutput, RevenueQuery
from reporting.services import revenue


def cash_receive(request, data, pk):
    m, p = payment.receive_cash(request.user, member.get_member(pk), data["plan_id"])
    return {
        "member": member.admin_member_data(member.get_member(m.user_id)),
        "payment": PaymentSerializer(p).data,
    }


def cash_request_accept(request, data, pk):
    req, p, m = payment.accept_cash_request(request.user, pk)
    return {
        "request": CashPaymentRequestSerializer(req).data,
        "member": member.admin_member_data(member.get_member(m.user_id)),
        "payment": PaymentSerializer(p).data,
    }


def mfa_enroll(request, data, pk):
    with transaction.atomic():
        user = staff_by_id(pk)
        if not user.is_active:
            from rest_framework.exceptions import NotFound

            raise NotFound("Staff not found.")
        auth.User.objects.select_for_update().get(pk=user.pk)
        return auth.begin_mfa(user)


api = [
    path("public/plans/", PublicPlanList.as_view()),
    path("auth/", include("accounts.urls")),
    path("users/", include("fitness.urls")),
    path("workouts/", include("workouts.urls")),
    path("schedules/", include("schedules.urls")),
    path("nutrition/", include("nutrition.urls")),
    path("journal/", include("journal.urls")),
    path("feed/", include("fitness.feed_urls")),
    path("music/", include("music.urls")),
    path(
        "welcome/",
        endpoint(
            "public_welcome",
            response=inline_serializer(
                "Welcome",
                fields={
                    "app_name": serializers.CharField(),
                    "environment": serializers.CharField(),
                    "message": serializers.CharField(),
                },
            ),
            handler=lambda r, d: {
                "app_name": "GYMA",
                "environment": settings.APP_ENV,
                "message": "Welcome to GYMA.",
            },
            method="get",
        ),
    ),
    path("member/profile/", ProfileView.as_view()),
    path(
        "member/profile/complete/",
        endpoint(
            "member_complete_profile",
            response=ProfileOutput,
            handler=lambda r, d: member.save_profile(r.user, d, complete=True),
            request=ProfileInput,
            permission=MemberOnly,
        ),
    ),
    path(
        "member/profile/phone/change/",
        endpoint(
            "member_change_phone",
            response=ProfileOutput,
            handler=lambda r, d: member.change_phone(r.user, d["phone_proof_token"]),
            request=auth_s.ProofInput,
            permission=MemberOnly,
        ),
    ),
    path(
        "member/profile/phone/recover-email/",
        endpoint(
            "member_recover_email",
            response=RecoveryOutput,
            handler=lambda r, d: member.recover_email(r.user),
            permission=MemberOnly,
        ),
    ),
    path("member/profile/photo/", PhotoView.as_view()),
    path(
        "member/profile/link-google/",
        endpoint(
            "member_link_google",
            response=auth_s.MemberOutput,
            handler=lambda r, d: member.link_google(r.user, d["id_token"]),
            request=auth_s.GoogleInput,
            permission=MemberOnly,
        ),
    ),
    path("member/plans/", MemberPlanList.as_view()),
    path("member/plans/<uuid:pk>/", MemberPlanDetail.as_view()),
    path(
        "member/dashboard/",
        endpoint(
            "member_dashboard",
            response=DashboardOutput,
            handler=lambda r, d: member.dashboard(r.user),
            method="get",
            permission=MemberOnly,
        ),
    ),
    path(
        "member/gym-status/",
        endpoint(
            "member_gym_status",
            response=GymStatusOutput,
            handler=lambda r, d: ops.gym_status(),
            method="get",
            permission=MemberOnly,
        ),
    ),
    path(
        "member/attendance/",
        endpoint(
            "member_attendance",
            response=MonthOutput,
            handler=lambda r, d: month_attendance(r.user, **d),
            method="get",
            request=MonthInput,
            permission=MemberOnly,
            parameters=query_parameters("year", "month"),
        ),
    ),
    path(
        "member/attendance/session/",
        endpoint(
            "member_attendance_session_adjust",
            response=MonthOutput,
            handler=lambda r, d: member_adjust_session(r.user, d),
            method="post",
            request=MemberSessionAdjustInput,
            permission=MemberOnly,
        ),
    ),
    path(
        "member/payments/sessions/",
        endpoint(
            "payments_create_session",
            handler=lambda r, d: SessionSerializer(payment.create_session(r.user, d)).data,
            request=SessionInput,
            response=SessionSerializer,
            permission=MemberOnly,
            status=201,
        ),
    ),
    path(
        "member/payments/sessions/<str:tran_id>/",
        endpoint(
            "payments_get_session",
            handler=lambda r, d, tran_id: (
                SessionSerializer(payment.confirm_session(r.user, tran_id, poll=True)).data
            ),
            method="get",
            response=SessionSerializer,
            permission=MemberOnly,
        ),
    ),
    path(
        "member/payments/sessions/<str:tran_id>/confirm/",
        endpoint(
            "payments_confirm_session",
            handler=lambda r, d, tran_id: (
                SessionSerializer(payment.confirm_session(r.user, tran_id)).data
            ),
            response=SessionSerializer,
            permission=MemberOnly,
        ),
    ),
    path(
        "member/payments/cash-requests/",
        endpoint(
            "payments_create_cash_request",
            handler=lambda r, d: (
                MemberCashPaymentRequestSerializer(payment.create_cash_request(r.user, d)).data
            ),
            request=PlanInput,
            response=MemberCashPaymentRequestSerializer,
            permission=MemberOnly,
            status=201,
        ),
    ),
    path(
        "member/payments/cash-requests/list/",
        endpoint(
            "payments_list_cash_requests",
            handler=lambda r, d: (
                MemberCashPaymentRequestSerializer(
                    payment.list_member_cash_requests(r.user, d.get("status")),
                    many=True,
                ).data
            ),
            method="get",
            request=CashRequestStatusFilter,
            response=MemberCashPaymentRequestSerializer(many=True),
            permission=MemberOnly,
            parameters=query_parameters("status"),
        ),
    ),
    path(
        "member/payments/cash-requests/<uuid:pk>/",
        endpoint(
            "payments_get_cash_request",
            handler=lambda r, d, pk: (
                MemberCashPaymentRequestSerializer(
                    payment.get_cash_request_for_member(r.user, pk)
                ).data
            ),
            method="get",
            response=MemberCashPaymentRequestSerializer,
            permission=MemberOnly,
        ),
    ),
    path(
        "member/payments/cash-requests/<uuid:pk>/cancel/",
        endpoint(
            "payments_cancel_cash_request",
            handler=lambda r, d, pk: (
                MemberCashPaymentRequestSerializer(payment.cancel_cash_request(r.user, pk)).data
            ),
            response=MemberCashPaymentRequestSerializer,
            permission=MemberOnly,
        ),
    ),
    path("member/payments/", PaymentList.as_view()),
    path("member/payments/<uuid:pk>/", PaymentDetail.as_view()),
    path(
        "member/payments/<uuid:pk>/receipt/",
        endpoint(
            "payments_receipt_url",
            response=inline_serializer("ReceiptURL", fields={"url": serializers.URLField()}),
            handler=receipt,
            method="get",
            permission=MemberOnly,
        ),
    ),
    path(
        "member/payments/<uuid:pk>/receipt.html/",
        endpoint(
            "payments_receipt_html",
            handler=lambda r, d, pk: receipt(r, d, pk, html=True),
            method="get",
            response={(200, "text/html"): OpenApiTypes.STR},
            permission=MemberOnly,
        ),
    ),
    path(
        "webhooks/sslcommerz/ipn/",
        endpoint(
            "payments_sslcommerz_ipn",
            response=inline_serializer(
                "IPNReceived", fields={"received": serializers.BooleanField()}
            ),
            handler=lambda r, d: payment.handle_ipn(d),
            request=IPNInput,
            authentication=[],
            throttle_public=False,
        ),
    ),
    path(
        "internal/attendance/check-in/",
        endpoint(
            "attendance_check_in",
            response=CheckInOutput,
            handler=lambda r, d: record_checkin(d),
            request=CheckInInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
        ),
    ),
    path(
        "internal/attendance/check-out/",
        endpoint(
            "attendance_check_out",
            response=CheckInOutput,
            handler=lambda r, d: record_checkout(d),
            request=CheckInInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
        ),
    ),
    path(
        "internal/biometrics/vault-members/",
        endpoint(
            "internal_vault_members",
            response=VaultMembersOutput,
            handler=lambda r, d: bio.list_vault_members(),
            method="get",
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
        ),
    ),
    path(
        "internal/biometrics/vault-push/",
        endpoint(
            "internal_vault_push",
            response=VaultBulkPushOutput,
            handler=lambda r, d: bio.push_vault_bulk(
                bridge_device_id=d["bridge_device_id"],
                member_ids=d.get("member_ids"),
            ),
            request=VaultBulkPushInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
        ),
    ),
    path("admin/members/", AdminMemberList.as_view()),
    path("admin/members/<uuid:pk>/", AdminMemberDetail.as_view()),
    path(
        "admin/members/<uuid:pk>/phone/",
        endpoint(
            "admin_link_member_phone",
            response=AdminMemberOutput,
            handler=lambda r, d, pk: member.admin_link_phone(r.user, member.get_member(pk), d),
            request=auth_s.VerifyInput,
            permission=StaffPermission("members.update"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/fingerprint/",
        endpoint(
            "admin_member_fingerprint",
            response=AdminMemberOutput,
            handler=lambda r, d, pk: member.set_fingerprint(
                r.user, member.get_member(pk), d["status"]
            ),
            request=FingerprintInput,
            permission=StaffPermission("members.update"),
        ),
    ),
    path(
        "admin/device/status/",
        endpoint(
            "admin_device_status",
            response=DeviceStatusOutput,
            handler=lambda r, d: bio.status_payload(),
            method="get",
            permission=StaffPermission("device_controllers.view"),
        ),
    ),
    path("admin/device/controllers/", DeviceControllersList.as_view()),
    path(
        "admin/device/controllers/<uuid:staff_id>/",
        endpoint(
            "admin_device_controllers_remove",
            response=DeviceControllerRemovedOutput,
            handler=lambda r, d, staff_id: bio.remove_device_controller(
                r.user, bio.device_controller_input_staff(staff_id)
            ),
            method="delete",
            permission=StaffPermission("device_controllers.delete"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/fingerprint/templates/",
        endpoint(
            "admin_member_fingerprint_templates",
            response=MemberTemplatesOutput,
            handler=lambda r, d, pk: bio.list_member_templates(member.get_member(pk)),
            method="get",
            permission=StaffPermission("members.view"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/fingerprint/templates/<int:finger_id>/",
        endpoint(
            "admin_member_fingerprint_template_delete",
            response=MemberTemplatesOutput,
            handler=lambda r, d, pk, finger_id: bio.delete_member_template(
                r.user, member.get_member(pk), finger_id
            ),
            method="delete",
            permission=StaffPermission("members.delete"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/fingerprint/enroll/",
        endpoint(
            "admin_member_fingerprint_enroll",
            response=EnrollInteractiveOutput,
            handler=lambda r, d, pk: bio.enroll_interactive(
                r.user,
                member.get_member(pk),
                d["finger_id"],
                pin=d.get("pin", "") or "",
                device_id=(d.get("device_id") or None) or None,
            ),
            request=EnrollInteractiveInput,
            permission=StaffPermission("members.update"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/fingerprint/pull/",
        endpoint(
            "admin_member_fingerprint_pull",
            response=VaultSyncOutput,
            handler=lambda r, d, pk: bio.pull_templates(r.user, member.get_member(pk)),
            permission=StaffPermission("members.update"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/fingerprint/push/",
        endpoint(
            "admin_member_fingerprint_push",
            response=VaultSyncOutput,
            handler=lambda r, d, pk: bio.push_vault_to_device(r.user, member.get_member(pk)),
            permission=StaffPermission("members.update"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/cash-preview/",
        endpoint(
            "admin_cash_preview",
            response=CashPreviewOutput,
            handler=lambda r, d, pk: payment.cash_preview(
                r.user, member.get_member(pk), d["plan_id"]
            ),
            method="get",
            request=PlanInput,
            permission=StaffPermission("members.update"),
            parameters=query_parameters("plan_id"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/cash-payments/",
        endpoint(
            "admin_cash_payment",
            response=inline_serializer(
                "CashReceive",
                fields={"member": AdminMemberOutput(), "payment": PaymentSerializer()},
            ),
            handler=cash_receive,
            request=PlanInput,
            permission=StaffPermission("members.update"),
            status=201,
        ),
    ),
    path(
        "admin/cash-requests/",
        endpoint(
            "admin_list_cash_requests",
            handler=lambda r, d: (
                CashPaymentRequestSerializer(
                    payment.list_admin_cash_requests(r.user, d.get("status") or "pending"),
                    many=True,
                ).data
            ),
            method="get",
            request=CashRequestStatusFilter,
            response=CashPaymentRequestSerializer(many=True),
            permission=StaffPermission("members.view"),
            parameters=query_parameters("status"),
        ),
    ),
    path(
        "admin/members/<uuid:pk>/cash-requests/",
        endpoint(
            "admin_member_cash_requests",
            handler=lambda r, d, pk: (
                CashPaymentRequestSerializer(
                    payment.list_member_admin_cash_requests(r.user, member.get_member(pk)),
                    many=True,
                ).data
            ),
            method="get",
            response=CashPaymentRequestSerializer(many=True),
            permission=StaffPermission("members.view"),
        ),
    ),
    path(
        "admin/cash-requests/<uuid:pk>/accept/",
        endpoint(
            "admin_accept_cash_request",
            response=inline_serializer(
                "CashRequestAccept",
                fields={
                    "request": CashPaymentRequestSerializer(),
                    "member": AdminMemberOutput(),
                    "payment": PaymentSerializer(),
                },
            ),
            handler=cash_request_accept,
            permission=StaffPermission("members.update"),
        ),
    ),
    path(
        "admin/cash-requests/<uuid:pk>/reject/",
        endpoint(
            "admin_reject_cash_request",
            handler=lambda r, d, pk: (
                CashPaymentRequestSerializer(payment.reject_cash_request(r.user, pk)).data
            ),
            response=CashPaymentRequestSerializer,
            permission=StaffPermission("members.update"),
        ),
    ),
    path("admin/plans/", PlanList.as_view()),
    path("admin/plans/<uuid:pk>/", PlanDetail.as_view()),
    path("admin/plans/<uuid:pk>/offers/", OfferList.as_view()),
    path("admin/plans/<uuid:pk>/offers/<uuid:offer_id>/", OfferDetail.as_view()),
    path(
        "admin/staff/permissions/catalog/",
        endpoint(
            "admin_staff_permissions_catalog",
            response=inline_serializer(
                "StaffPermissionCatalog",
                fields={
                    "features": inline_serializer(
                        "StaffPermissionFeature",
                        fields={
                            "feature": serializers.CharField(),
                            "actions": serializers.ListField(child=serializers.CharField()),
                        },
                        many=True,
                    )
                },
            ),
            handler=lambda r, d: {"features": catalog_payload()},
            method="get",
            permission=SuperOnly,
        ),
    ),
    path("admin/staff/", StaffList.as_view()),
    path("admin/staff/<uuid:pk>/", StaffDetail.as_view()),
    path(
        "admin/staff/<uuid:pk>/activate/",
        endpoint(
            "admin_staff_activate",
            handler=lambda r, d, pk: (
                StaffSerializer(ops.set_staff_active(r.user, staff_by_id(pk), True)).data
            ),
            permission=SuperOnly,
            response=StaffSerializer,
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/deactivate/",
        endpoint(
            "admin_staff_deactivate",
            handler=lambda r, d, pk: (
                StaffSerializer(ops.set_staff_active(r.user, staff_by_id(pk), False)).data
            ),
            permission=SuperOnly,
            response=StaffSerializer,
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/mfa/enroll/",
        endpoint(
            "admin_staff_mfa_enroll",
            response=auth_s.MFAEnrollOutput,
            handler=mfa_enroll,
            permission=SuperOnly,
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/fingerprint/templates/",
        endpoint(
            "admin_staff_fingerprint_templates",
            response=StaffTemplatesOutput,
            handler=lambda r, d, pk: bio.list_staff_templates(
                bio.staff_profile_for_user(staff_by_id(pk))
            ),
            method="get",
            permission=StaffPermission("staff.view"),
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/fingerprint/templates/<int:finger_id>/",
        endpoint(
            "admin_staff_fingerprint_template_delete",
            response=StaffTemplatesOutput,
            handler=lambda r, d, pk, finger_id: bio.delete_staff_template(
                r.user, bio.staff_profile_for_user(staff_by_id(pk)), finger_id
            ),
            method="delete",
            permission=SuperOnly,
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/fingerprint/enroll/",
        endpoint(
            "admin_staff_fingerprint_enroll",
            response=StaffEnrollInteractiveOutput,
            handler=lambda r, d, pk: bio.enroll_staff_interactive(
                r.user,
                bio.staff_profile_for_user(staff_by_id(pk)),
                d["finger_id"],
                device_id=(d.get("device_id") or None) or None,
            ),
            request=EnrollInteractiveInput,
            permission=SuperOnly,
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/fingerprint/pull/",
        endpoint(
            "admin_staff_fingerprint_pull",
            response=VaultSyncOutput,
            handler=lambda r, d, pk: bio.pull_staff_templates(
                r.user, bio.staff_profile_for_user(staff_by_id(pk))
            ),
            permission=SuperOnly,
        ),
    ),
    path(
        "admin/staff/<uuid:pk>/fingerprint/push/",
        endpoint(
            "admin_staff_fingerprint_push",
            response=VaultSyncOutput,
            handler=lambda r, d, pk: bio.push_staff_vault_to_device(
                r.user, bio.staff_profile_for_user(staff_by_id(pk))
            ),
            permission=SuperOnly,
        ),
    ),
    path("admin/costs/", CostList.as_view()),
    path("admin/costs/<uuid:pk>/", CostDetail.as_view()),
    path(
        "admin/costs/<uuid:pk>/archive/",
        endpoint(
            "admin_cost_archive",
            handler=lambda r, d, pk: (
                CostSerializer(
                    ops.mutate_cost(r.user, get_object_or_404(ops.Cost, pk=pk), "archive")
                ).data
            ),
            permission=StaffPermission("costs.update"),
            response=CostSerializer,
        ),
    ),
    path("admin/activity/", ActivityList.as_view()),
    path(
        "admin/gym-hours/",
        endpoint(
            "admin_gym_hours",
            response=GymHoursOutput,
            handler=lambda r, d: {
                "week": ops.week_data(),
                "holidays": [ops.holiday_data(h) for h in ops.Holiday.objects.order_by("date")],
            },
            method="get",
            permission=StaffPermission("gym_hours.view"),
        ),
    ),
    path(
        "admin/gym-hours/week/",
        endpoint(
            "admin_gym_week_update",
            response=GymHoursOutput,
            handler=lambda r, d: ops.put_week(r.user, d["week"]),
            method="put",
            request=WeekInput,
            permission=StaffPermission("gym_hours.update"),
        ),
    ),
    path("admin/gym-hours/holidays/", HolidayList.as_view()),
    path("admin/gym-hours/holidays/<uuid:pk>/", HolidayDetail.as_view()),
    path(
        "admin/revenue/",
        endpoint(
            "admin_revenue",
            response=RevenueOutput,
            handler=lambda r, d: revenue(r.user, d),
            method="get",
            request=RevenueQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters(
                "range", "date", "from", "to", "dates", "member_id", "channel", "limit"
            ),
        ),
    ),
]
urlpatterns = [
    path("api/v1/", include(api)),
    path("api/", include(api)),
    path("admin/", admin.site.urls),
    path("", public.landing),
    path("terms/", public.legal, {"page": "terms"}),
    path("privacy/", public.legal, {"page": "privacy"}),
    path("health/", public.health),
    path("health/live/", public.live),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path(
        "openapi.yaml",
        SpectacularAPIView.as_view(authentication_classes=[], permission_classes=[AllowAny]),
        name="schema",
    ),
    path("media/member-photos/<str:filename>", public.photo),
    path("payments/return/<str:outcome>/", public.payment_return),
]

handler404 = "core.public.not_found"
handler500 = "core.public.server_error"

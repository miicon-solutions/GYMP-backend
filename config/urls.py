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
from attendance.authentication import DeviceAuthentication
from attendance.serializers import CheckInInput, CheckInOutput, MonthInput, MonthOutput
from attendance.services import month_attendance, record_checkin
from core import public
from core.api import AdminOnly, MemberOnly, SuperOnly
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
    GymHoursOutput,
    GymStatusOutput,
    StaffSerializer,
    WeekInput,
)
from operations.views import (
    ActivityList,
    CostDetail,
    CostList,
    HolidayDetail,
    HolidayList,
    StaffDetail,
    StaffList,
    staff_by_id,
)
from payments import services as payment
from payments.serializers import (
    CashPreviewOutput,
    IPNInput,
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
)
from reporting.serializers import RevenueOutput, RevenueQuery
from reporting.services import revenue


def cash_receive(request, data, pk):
    m, p = payment.receive_cash(request.user, member.get_member(pk), data["plan_id"])
    return {
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
    path("auth/", include("accounts.urls")),
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
    path("admin/members/", AdminMemberList.as_view()),
    path("admin/members/<uuid:pk>/", AdminMemberDetail.as_view()),
    path(
        "admin/members/<uuid:pk>/phone/",
        endpoint(
            "admin_link_member_phone",
            response=AdminMemberOutput,
            handler=lambda r, d, pk: member.admin_link_phone(r.user, member.get_member(pk), d),
            request=auth_s.VerifyInput,
            permission=AdminOnly,
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
            permission=AdminOnly,
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
            permission=AdminOnly,
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
            permission=AdminOnly,
            status=201,
        ),
    ),
    path("admin/plans/", PlanList.as_view()),
    path("admin/plans/<uuid:pk>/", PlanDetail.as_view()),
    path("admin/plans/<uuid:pk>/offers/", OfferList.as_view()),
    path("admin/plans/<uuid:pk>/offers/<uuid:offer_id>/", OfferDetail.as_view()),
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
            permission=AdminOnly,
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
            permission=AdminOnly,
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
            permission=AdminOnly,
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
            permission=AdminOnly,
            parameters=query_parameters(
                "range", "date", "from", "to", "dates", "member_id", "channel", "limit"
            ),
        ),
    ),
]
urlpatterns = [
    path("api/v1/", include(api)),
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

from django.conf import settings
from django.contrib import admin
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import include, path
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, inline_serializer
from drf_spectacular.views import SpectacularSwaggerView
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
from biometrics import jobs as bridge_jobs
from biometrics import services as bio
from biometrics.serializers import (
    BridgeHeartbeatInput,
    BridgeHeartbeatOutput,
    BridgeJobCompleteInput,
    BridgeJobCompleteOutput,
    BridgeJobsClaimOutput,
    BridgeJobsClaimQuery,
    BridgePingOutput,
    DeviceStatusOutput,
    EnrollInteractiveInput,
    EnrollInteractiveOutput,
    MemberTemplatesOutput,
    StaffEnrollInteractiveOutput,
    StaffTemplatesOutput,
    VaultBulkPushInput,
    VaultBulkPushOutput,
    VaultExportInput,
    VaultExportOutput,
    VaultMembersOutput,
    VaultSyncAckInput,
    VaultSyncAckOutput,
    VaultSyncOutput,
)
from core import public
from core.api import AdminOnly, MemberOnly, StaffPermission, SuperOnly
from core.api_docs import (
    DocsScalarFrameView,
    DocsSwaggerFrameView,
    DocsUIView,
    FeaturePackView,
    FeatureSchemaView,
    FeaturesIndexView,
    VersionedSchemaView,
)
from core.endpoints import ObjectResponse, endpoint, query_parameters
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
from reporting.serializers import (
    ChannelDateQuery,
    MembershipStatusQuery,
    ReportDateQuery,
    RevenueOutput,
    RevenueQuery,
)
from reporting.services import (
    admission_report,
    cash_vs_online,
    expenses_by_admin,
    member_collections,
    membership_status,
    plan_mix,
    revenue,
    revenue_vs_expense,
)


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


def _bridge_heartbeat(data):
    device = bridge_jobs.record_heartbeat(data)
    return {
        "ok": True,
        "bridge_device_id": device.bridge_device_id or "",
        "last_seen_at": device.last_seen_at,
    }


def _bridge_claim_jobs(_request, data):
    claimed = bridge_jobs.claim_next(
        bridge_device_id=data.get("bridge_device_id") or None,
        limit=int(data.get("limit") or 1),
        wait_sec=float(data.get("wait") or 0),
    )
    return {
        "count": len(claimed),
        "jobs": [bridge_jobs.job_wire(job) for job in claimed],
    }


def _bridge_claim_one(request, _data, pk):
    from biometrics.models import BridgeDeviceJob
    from rest_framework.exceptions import NotFound, ValidationError

    bid = (request.query_params.get("bridge_device_id") or "").strip()
    with transaction.atomic():
        try:
            job = BridgeDeviceJob.objects.select_for_update().get(pk=pk)
        except BridgeDeviceJob.DoesNotExist as exc:
            raise NotFound("Bridge job not found.") from exc
        if job.status != BridgeDeviceJob.STATUS_PENDING:
            raise ValidationError({"status": "Job is not pending."})
        from django.utils import timezone

        now = timezone.now()
        if job.expires_at and job.expires_at <= now:
            job.status = BridgeDeviceJob.STATUS_EXPIRED
            job.error = "Bridge job expired before completion."
            job.completed_at = now
            job.save(update_fields=["status", "error", "completed_at", "updated_at"])
            raise ValidationError({"status": "Job expired."})
        job.status = BridgeDeviceJob.STATUS_CLAIMED
        job.claimed_at = now
        if bid and not job.bridge_device_id:
            job.bridge_device_id = bid
        job.save(update_fields=["status", "claimed_at", "bridge_device_id", "updated_at"])
    return {"count": 1, "jobs": [bridge_jobs.job_wire(job)]}


def _bridge_complete_job(pk, data):
    job = bridge_jobs.complete_job(
        pk,
        status=data["status"],
        result=data.get("result") or {},
        error=data.get("error") or "",
    )
    return {"ok": True, "id": job.id, "status": job.status}


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
    path("", include("notifications.urls")),
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
            tags=["public"],
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
            tags=["payments"],
            examples=[
                OpenApiExample(
                    "Hosted checkout",
                    value={
                        "kind": "first_purchase",
                        "plan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "checkout": "hosted",
                    },
                    request_only=True,
                ),
            ],
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
            tags=["payments"],
            examples=[
                OpenApiExample(
                    "Cash request",
                    value={"plan_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"},
                    request_only=True,
                ),
            ],
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
            tags=["attendance"],
            examples=[
                OpenApiExample(
                    "Device check-in",
                    value={
                        "member_id": "PF-0001",
                        "source": "device",
                        "checked_in_at": None,
                    },
                    request_only=True,
                ),
            ],
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
            tags=["attendance"],
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
            tags=["device"],
        ),
    ),
    path(
        "internal/biometrics/vault-export/",
        endpoint(
            "internal_vault_export",
            response=VaultExportOutput,
            handler=lambda r, d: bio.export_vault(
                member_ids=d.get("member_ids"),
                include_staff=bool(d.get("include_staff", True)),
            ),
            request=VaultExportInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
        ),
    ),
    path(
        "internal/biometrics/vault-sync-ack/",
        endpoint(
            "internal_vault_sync_ack",
            response=VaultSyncAckOutput,
            handler=lambda r, d: bio.ack_vault_sync(
                bridge_device_id=d["bridge_device_id"],
                member_ids=d.get("member_ids"),
                staff_ids=d.get("staff_ids"),
                failures=d.get("failures"),
            ),
            request=VaultSyncAckInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
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
            tags=["device"],
        ),
    ),
    path(
        "internal/bridge/ping/",
        endpoint(
            "internal_bridge_ping",
            response=BridgePingOutput,
            handler=lambda r, d: {
                "ok": True,
                "bridge_connected": True,
                "scanner_online": False,
                "message": "GYMP-backend reachable; device key accepted.",
                "last_seen_at": None,
                "heartbeat_age_sec": None,
                "bridge_device_id": "",
            },
            method="get",
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
        ),
    ),
    path(
        "internal/bridge/heartbeat/",
        endpoint(
            "internal_bridge_heartbeat",
            response=BridgeHeartbeatOutput,
            handler=lambda r, d: _bridge_heartbeat(d),
            request=BridgeHeartbeatInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
        ),
    ),
    path(
        "internal/bridge/jobs/",
        endpoint(
            "internal_bridge_jobs_claim",
            response=BridgeJobsClaimOutput,
            handler=_bridge_claim_jobs,
            method="get",
            request=BridgeJobsClaimQuery,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
            parameters=query_parameters("bridge_device_id", "limit", "wait"),
        ),
    ),
    path(
        "internal/bridge/jobs/<uuid:pk>/claim/",
        endpoint(
            "internal_bridge_job_claim",
            response=BridgeJobsClaimOutput,
            handler=_bridge_claim_one,
            method="post",
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
            parameters=query_parameters("bridge_device_id"),
        ),
    ),
    path(
        "internal/bridge/jobs/<uuid:pk>/complete/",
        endpoint(
            "internal_bridge_job_complete",
            response=BridgeJobCompleteOutput,
            handler=lambda r, d, pk: _bridge_complete_job(pk, d),
            request=BridgeJobCompleteInput,
            permission=AllowAny,
            authentication=[DeviceAuthentication],
            throttle_public=False,
            tags=["device"],
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
            # Any staff may probe reachability so fingerprint UIs can gate
            # enroll/delete without requiring device_controllers.view.
            permission=AdminOnly,
        ),
    ),
    path(
        "admin/device/ping/",
        endpoint(
            "admin_device_ping",
            response=BridgePingOutput,
            handler=lambda r, d: bio.bridge_ping_payload(),
            method="get",
            permission=AdminOnly,
            tags=["device"],
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
            permission=StaffPermission("cash_requests.view"),
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
            permission=StaffPermission("cash_requests.view"),
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
            permission=StaffPermission("cash_requests.update"),
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
            permission=StaffPermission("cash_requests.update"),
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
    path(
        "admin/reports/cash-vs-online/",
        endpoint(
            "admin_report_cash_vs_online",
            response=ObjectResponse,
            handler=lambda r, d: cash_vs_online(r.user, d),
            method="get",
            request=ReportDateQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("range", "date", "from", "to", "dates"),
        ),
    ),
    path(
        "admin/reports/member-collections/",
        endpoint(
            "admin_report_member_collections",
            response=ObjectResponse,
            handler=lambda r, d: member_collections(r.user, d),
            method="get",
            request=ChannelDateQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("range", "date", "from", "to", "dates", "channel"),
        ),
    ),
    path(
        "admin/reports/revenue-vs-expense/",
        endpoint(
            "admin_report_revenue_vs_expense",
            response=ObjectResponse,
            handler=lambda r, d: revenue_vs_expense(r.user, d),
            method="get",
            request=ReportDateQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("range", "date", "from", "to", "dates"),
        ),
    ),
    path(
        "admin/reports/membership-status/",
        endpoint(
            "admin_report_membership_status",
            response=ObjectResponse,
            handler=lambda r, d: membership_status(r.user, d),
            method="get",
            request=MembershipStatusQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("within_days"),
        ),
    ),
    path(
        "admin/reports/expenses-by-admin/",
        endpoint(
            "admin_report_expenses_by_admin",
            response=ObjectResponse,
            handler=lambda r, d: expenses_by_admin(r.user, d),
            method="get",
            request=ReportDateQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("range", "date", "from", "to", "dates"),
        ),
    ),
    path(
        "admin/reports/admission/",
        endpoint(
            "admin_report_admission",
            response=ObjectResponse,
            handler=lambda r, d: admission_report(r.user, d),
            method="get",
            request=ReportDateQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("range", "date", "from", "to", "dates"),
        ),
    ),
    path(
        "admin/reports/plan-mix/",
        endpoint(
            "admin_report_plan_mix",
            response=ObjectResponse,
            handler=lambda r, d: plan_mix(r.user, d),
            method="get",
            request=ChannelDateQuery,
            permission=StaffPermission("reports.view"),
            parameters=query_parameters("range", "date", "from", "to", "dates", "channel"),
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
    path("docs/", DocsUIView.as_view(), name="docs"),
    path("docs/v1/", DocsUIView.as_view(), {"version": "v1"}, name="docs-v1"),
    path(
        "docs/v1/reference/",
        DocsScalarFrameView.as_view(),
        {"version": "v1"},
        name="docs-v1-reference",
    ),
    path(
        "docs/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema-json"),
        name="docs-swagger",
    ),
    path(
        "docs/swagger/frame/",
        DocsSwaggerFrameView.as_view(),
        name="docs-swagger-frame",
    ),
    path("docs/features/", FeaturesIndexView.as_view(), name="docs-features"),
    path(
        "docs/features/<slug:feature>/",
        FeaturePackView.as_view(),
        name="docs-feature-pack",
    ),
    path("openapi.yaml", VersionedSchemaView.as_view(), name="schema"),
    path("openapi.json", VersionedSchemaView.as_view(), name="schema-json"),
    path("openapi/v1.yaml", VersionedSchemaView.as_view(), {"version": "v1"}, name="schema-v1"),
    path("openapi/v1.json", VersionedSchemaView.as_view(), {"version": "v1"}, name="schema-v1-json"),
    path(
        "openapi/v1/<slug:feature>.yaml",
        FeatureSchemaView.as_view(),
        {"version": "v1"},
        name="schema-v1-feature",
    ),
    path(
        "openapi/v1/<slug:feature>.json",
        FeatureSchemaView.as_view(),
        {"version": "v1"},
        name="schema-v1-feature-json",
    ),
    path("media/member-photos/<str:filename>", public.photo),
    path("payments/return/<str:outcome>/", public.payment_return),
]

handler404 = "core.public.not_found"
handler500 = "core.public.server_error"

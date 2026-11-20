from django.contrib import admin, messages

from accounts.models import User
from core.admin import OperatorModelAdmin
from notifications.models import MemberDeviceToken, MemberNotification
from notifications.services import send_fcm_for_notification, send_sms_for_notification


@admin.register(MemberNotification)
class MemberNotificationAdmin(OperatorModelAdmin):
    """Operator console for in-app rows. Checking send_push/send_sms on Add also fires delivery."""

    list_display = (
        "id",
        "recipient",
        "code",
        "kind",
        "title",
        "is_unread",
        "send_push",
        "send_sms",
        "created_at",
    )
    list_filter = ("kind", "code", "is_unread", "send_push", "send_sms")
    search_fields = (
        "user__phone_e164",
        "user__full_name",
        "user__member_profile__member_id",
        "title",
        "title_key",
        "code",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ("send_fcm_now", "send_sms_now")
    fieldsets = (
        (
            "Recipient",
            {
                "fields": ("user",),
                "description": (
                    "Pick the same member who is signed into the app "
                    "(search by phone or PF- id). The feed is per-user — "
                    "a notification for Johnson will not appear for Mike."
                ),
            },
        ),
        (
            "Message (free text — easiest for tests)",
            {
                "fields": ("title", "body", "kind", "code"),
                "description": (
                    "For announcements use code=announcement and kind=general. "
                    "Free-text title/body are shown as-is in the app."
                ),
            },
        ),
        (
            "ARB keys (optional)",
            {
                "classes": ("collapse",),
                "fields": ("title_key", "body_key", "title_params", "body_params"),
            },
        ),
        (
            "Flags",
            {
                "fields": (
                    "is_unread",
                    "send_push",
                    "send_sms",
                    "related_object_id",
                    "dedupe_key",
                ),
                "description": (
                    "Check Send push / Send sms on Add to deliver after save. "
                    "Or use the list actions “Send FCM now” / “Send SMS now”."
                ),
            },
        ),
        ("System", {"classes": ("collapse",), "fields": ("id", "created_at", "updated_at")}),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if obj is not None:
            return fieldsets
        # Add form: OperatorModelAdmin drops updated_at from readonly; auto_now
        # fields cannot appear as normal form fields. Hide System on create.
        return [fs for fs in fieldsets if fs[0] != "System"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user", "user__member_profile")
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(role="member").order_by(
                "full_name", "phone_e164"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Recipient", ordering="user__phone_e164")
    def recipient(self, obj):
        user = obj.user
        profile = getattr(user, "member_profile", None)
        member_id = getattr(profile, "member_id", None) or "—"
        return f"{user.full_name or '—'} · {user.phone_e164} · {member_id}"

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("kind", "general")
        initial.setdefault("code", "announcement")
        initial.setdefault("is_unread", True)
        initial.setdefault("send_push", True)
        initial.setdefault("send_sms", False)
        initial.setdefault("title", "Test notification")
        initial.setdefault("body", "Hello from Pure Fitness admin.")
        return initial

    def save_model(self, request, obj, form, change):
        previous_send_push = False
        previous_send_sms = False
        if change and obj.pk:
            previous = (
                MemberNotification.objects.filter(pk=obj.pk)
                .values("send_push", "send_sms")
                .first()
                or {}
            )
            previous_send_push = bool(previous.get("send_push"))
            previous_send_sms = bool(previous.get("send_sms"))
        super().save_model(request, obj, form, change)
        should_push = obj.send_push and (not change or not previous_send_push)
        if should_push:
            self._report_fcm_result(request, send_fcm_for_notification(obj.pk))
        should_sms = obj.send_sms and (not change or not previous_send_sms)
        if should_sms:
            self._report_sms_result(request, send_sms_for_notification(obj.pk))

    def _report_fcm_result(self, request, result: dict) -> None:
        skipped = result.get("skipped")
        if skipped == "no_device":
            messages.warning(
                request,
                "In-app saved, but no FCM device token for this member. "
                "Open the app signed-in and accept notification permission.",
            )
        elif skipped == "push_disabled":
            messages.warning(
                request,
                "In-app saved, but member push_enabled is off.",
            )
        elif skipped == "missing":
            messages.error(request, "Notification disappeared before FCM send.")
        elif result.get("sent", 0) > 0:
            messages.success(
                request,
                f"FCM sent to {result['sent']} device(s)"
                + (f" ({result['failed']} failed)." if result.get("failed") else "."),
            )
        elif result.get("failed", 0) > 0:
            detail = "; ".join(result.get("errors") or []) or "Check Firebase/APNs."
            messages.error(
                request,
                f"FCM failed for {result['failed']} device(s): {detail}",
            )

    def _report_sms_result(self, request, result: dict) -> None:
        skipped = result.get("skipped")
        if skipped == "sms_disabled":
            messages.warning(request, "In-app saved, but member sms_enabled is off.")
        elif skipped == "no_phone":
            messages.warning(request, "In-app saved, but member has no phone.")
        elif skipped == "missing":
            messages.error(request, "Notification disappeared before SMS send.")
        elif result.get("sent", 0) > 0:
            messages.success(request, "SMS sent.")
        elif result.get("failed", 0) > 0:
            detail = "; ".join(result.get("errors") or []) or "Check SMS_NET_BD_*."
            messages.error(request, f"SMS failed: {detail}")

    @admin.action(description="Send FCM now")
    def send_fcm_now(self, request, queryset):
        total_sent = 0
        total_failed = 0
        skipped = []
        for notif in queryset:
            result = send_fcm_for_notification(notif.pk)
            total_sent += result.get("sent", 0)
            total_failed += result.get("failed", 0)
            if result.get("skipped"):
                skipped.append(f"{notif.pk}: {result['skipped']}")
            if not notif.send_push:
                notif.send_push = True
                notif.save(update_fields=["send_push", "updated_at"])
        if total_sent:
            messages.success(request, f"FCM sent to {total_sent} device(s).")
        if total_failed:
            messages.error(request, f"FCM failed for {total_failed} device(s).")
        if skipped:
            messages.warning(
                request,
                "Skipped: " + "; ".join(skipped[:10])
                + ("…" if len(skipped) > 10 else ""),
            )

    @admin.action(description="Send SMS now")
    def send_sms_now(self, request, queryset):
        total_sent = 0
        total_failed = 0
        skipped = []
        for notif in queryset:
            result = send_sms_for_notification(notif.pk)
            total_sent += result.get("sent", 0)
            total_failed += result.get("failed", 0)
            if result.get("skipped"):
                skipped.append(f"{notif.pk}: {result['skipped']}")
            if not notif.send_sms:
                notif.send_sms = True
                notif.save(update_fields=["send_sms", "updated_at"])
        if total_sent:
            messages.success(request, f"SMS sent to {total_sent} recipient(s).")
        if total_failed:
            messages.error(request, f"SMS failed for {total_failed} recipient(s).")
        if skipped:
            messages.warning(
                request,
                "Skipped: " + "; ".join(skipped[:10])
                + ("…" if len(skipped) > 10 else ""),
            )


@admin.register(MemberDeviceToken)
class MemberDeviceTokenAdmin(OperatorModelAdmin):
    list_display = ("id", "recipient", "platform", "updated_at", "token_preview")
    list_filter = ("platform",)
    search_fields = (
        "user__phone_e164",
        "user__full_name",
        "user__member_profile__member_id",
        "token",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("id", "created_at", "updated_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(role="member").order_by(
                "full_name", "phone_e164"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Recipient", ordering="user__phone_e164")
    def recipient(self, obj):
        user = obj.user
        profile = getattr(user, "member_profile", None)
        member_id = getattr(profile, "member_id", None) or "—"
        return f"{user.full_name or '—'} · {user.phone_e164} · {member_id}"

    @admin.display(description="Token")
    def token_preview(self, obj):
        token = obj.token or ""
        if len(token) <= 16:
            return token
        return f"…{token[-12:]}"

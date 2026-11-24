from django.contrib import admin

from biometrics.models import (
    BridgeDeviceJob,
    FingerprintDevice,
    FingerprintDeviceStaffSyncState,
    FingerprintDeviceSyncState,
    MemberBiometricTemplate,
    StaffBiometricTemplate,
)


@admin.register(FingerprintDevice)
class FingerprintDeviceAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "lan_ip",
        "port",
        "scanner_online",
        "is_active",
        "last_seen_at",
    ]
    list_filter = ["is_active", "scanner_online"]


@admin.register(BridgeDeviceJob)
class BridgeDeviceJobAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "status", "bridge_device_id", "created_at", "expires_at"]
    list_filter = ["kind", "status"]
    readonly_fields = ["payload", "result", "error", "claimed_at", "completed_at"]


@admin.register(MemberBiometricTemplate)
class MemberBiometricTemplateAdmin(admin.ModelAdmin):
    list_display = ["member", "finger_index", "algorithm", "enrolled_at"]
    readonly_fields = ["template_ciphertext", "template_sha256"]


@admin.register(StaffBiometricTemplate)
class StaffBiometricTemplateAdmin(admin.ModelAdmin):
    list_display = ["staff", "finger_index", "algorithm", "enrolled_at"]
    readonly_fields = ["template_ciphertext", "template_sha256"]


@admin.register(FingerprintDeviceSyncState)
class FingerprintDeviceSyncStateAdmin(admin.ModelAdmin):
    list_display = ["device", "member", "templates_synced_at", "pin_synced_at", "updated_at"]


@admin.register(FingerprintDeviceStaffSyncState)
class FingerprintDeviceStaffSyncStateAdmin(admin.ModelAdmin):
    list_display = ["device", "staff", "templates_synced_at", "updated_at"]

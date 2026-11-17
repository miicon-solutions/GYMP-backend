from django.contrib import admin

from biometrics.models import FingerprintDevice, FingerprintDeviceSyncState, MemberBiometricTemplate


@admin.register(FingerprintDevice)
class FingerprintDeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "lan_ip", "port", "is_active", "last_seen_at"]
    list_filter = ["is_active"]


@admin.register(MemberBiometricTemplate)
class MemberBiometricTemplateAdmin(admin.ModelAdmin):
    list_display = ["member", "finger_index", "algorithm", "enrolled_at"]
    readonly_fields = ["template_ciphertext", "template_sha256"]


@admin.register(FingerprintDeviceSyncState)
class FingerprintDeviceSyncStateAdmin(admin.ModelAdmin):
    list_display = ["device", "member", "templates_synced_at", "pin_synced_at", "updated_at"]

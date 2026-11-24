from rest_framework import serializers


class DeviceStatusOutput(serializers.Serializer):
    online = serializers.BooleanField()
    bridge_ok = serializers.BooleanField()
    name = serializers.CharField(allow_blank=True)
    serial = serializers.CharField(allow_blank=True)
    firmware = serializers.CharField(allow_blank=True)
    user_count = serializers.IntegerField()
    ip = serializers.CharField(allow_blank=True)
    port = serializers.IntegerField()
    message = serializers.CharField(allow_blank=True)
    last_seen_at = serializers.DateTimeField(allow_null=True, required=False)
    heartbeat_age_sec = serializers.IntegerField(allow_null=True, required=False)


class BridgePingOutput(serializers.Serializer):
    ok = serializers.BooleanField()
    bridge_connected = serializers.BooleanField()
    scanner_online = serializers.BooleanField()
    message = serializers.CharField(allow_blank=True)
    last_seen_at = serializers.DateTimeField(allow_null=True, required=False)
    heartbeat_age_sec = serializers.IntegerField(allow_null=True, required=False)
    bridge_device_id = serializers.CharField(allow_blank=True, required=False)


class EnrollPrepareInput(serializers.Serializer):
    """Legacy prepare-only body; interactive enroll prefers finger_id."""

    pin = serializers.CharField(required=False, allow_blank=True, max_length=16)
    finger_id = serializers.IntegerField(required=False, min_value=0, max_value=9)
    device_id = serializers.CharField(required=False, allow_blank=True)


class EnrollPrepareOutput(serializers.Serializer):
    prepared = serializers.BooleanField(required=False)
    message = serializers.CharField(required=False)
    enrolled = serializers.BooleanField(required=False)
    finger_id = serializers.IntegerField(required=False)
    stored = serializers.IntegerField(required=False)
    fingerprint_status = serializers.CharField(required=False)
    finger_indexes = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )


class EnrollInteractiveInput(serializers.Serializer):
    finger_id = serializers.IntegerField(min_value=0, max_value=9)
    pin = serializers.CharField(required=False, allow_blank=True, max_length=16)
    device_id = serializers.CharField(required=False, allow_blank=True)


class EnrollInteractiveOutput(serializers.Serializer):
    enrolled = serializers.BooleanField()
    finger_id = serializers.IntegerField()
    stored = serializers.IntegerField()
    fingerprint_status = serializers.CharField()
    finger_indexes = serializers.ListField(child=serializers.IntegerField())


class MemberTemplatesOutput(serializers.Serializer):
    finger_indexes = serializers.ListField(child=serializers.IntegerField())
    fingerprint_status = serializers.CharField()


# Staff vault uses the same wire shape as member templates / enroll.
StaffTemplatesOutput = MemberTemplatesOutput
StaffEnrollInteractiveOutput = EnrollInteractiveOutput


class VaultSyncOutput(serializers.Serializer):
    stored = serializers.IntegerField(required=False)
    pushed = serializers.BooleanField(required=False)
    template_count = serializers.IntegerField(required=False)
    fingerprint_status = serializers.CharField(required=False)
    finger_indexes = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )


class VaultMemberOutput(serializers.Serializer):
    member_id = serializers.CharField()
    name = serializers.CharField()
    finger_indexes = serializers.ListField(child=serializers.IntegerField())
    has_pin = serializers.BooleanField()
    fingerprint_status = serializers.CharField()


class VaultMembersOutput(serializers.Serializer):
    count = serializers.IntegerField()
    members = VaultMemberOutput(many=True)


class VaultBulkPushInput(serializers.Serializer):
    bridge_device_id = serializers.CharField()
    member_ids = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )


class VaultBulkFailure(serializers.Serializer):
    member_id = serializers.CharField()
    error = serializers.CharField()


class VaultBulkPushOutput(serializers.Serializer):
    pushed = serializers.IntegerField()
    failed = serializers.IntegerField()
    failures = VaultBulkFailure(many=True)


class BridgeHeartbeatInput(serializers.Serializer):
    bridge_device_id = serializers.CharField(required=False, allow_blank=True)
    online = serializers.BooleanField()
    name = serializers.CharField(required=False, allow_blank=True)
    serial = serializers.CharField(required=False, allow_blank=True)
    firmware = serializers.CharField(required=False, allow_blank=True)
    user_count = serializers.IntegerField(required=False, min_value=0, default=0)
    ip = serializers.CharField(required=False, allow_blank=True)
    port = serializers.IntegerField(required=False, min_value=1, max_value=65535, default=4370)


class BridgeHeartbeatOutput(serializers.Serializer):
    ok = serializers.BooleanField()
    bridge_device_id = serializers.CharField(allow_blank=True)
    last_seen_at = serializers.DateTimeField(allow_null=True)


class BridgeJobOutput(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField()
    payload = serializers.DictField()
    bridge_device_id = serializers.CharField(allow_blank=True)
    expires_at = serializers.CharField(allow_null=True, required=False)
    created_at = serializers.CharField(allow_null=True, required=False)


class BridgeJobsClaimQuery(serializers.Serializer):
    bridge_device_id = serializers.CharField(required=False, allow_blank=True, default="")
    limit = serializers.IntegerField(required=False, min_value=1, max_value=10, default=1)
    wait = serializers.FloatField(required=False, min_value=0, max_value=25, default=0)


class BridgeJobsClaimOutput(serializers.Serializer):
    count = serializers.IntegerField()
    jobs = BridgeJobOutput(many=True)


class BridgeJobCompleteInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=["succeeded", "failed"])
    result = serializers.DictField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)


class BridgeJobCompleteOutput(serializers.Serializer):
    ok = serializers.BooleanField()
    id = serializers.UUIDField()
    status = serializers.CharField()


class VaultExportInput(serializers.Serializer):
    bridge_device_id = serializers.CharField(required=False, allow_blank=True)
    member_ids = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    include_staff = serializers.BooleanField(required=False, default=True)


class VaultExportUser(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["member", "staff"])
    user_id = serializers.CharField()
    name = serializers.CharField()
    pin = serializers.CharField(allow_blank=True)
    privilege = serializers.IntegerField()
    templates = serializers.DictField(child=serializers.CharField())


class VaultExportOutput(serializers.Serializer):
    count = serializers.IntegerField()
    users = VaultExportUser(many=True)


class VaultSyncAckInput(serializers.Serializer):
    bridge_device_id = serializers.CharField()
    member_ids = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    staff_ids = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    failures = VaultBulkFailure(many=True, required=False)


class VaultSyncAckOutput(serializers.Serializer):
    ok = serializers.BooleanField()
    synced_members = serializers.IntegerField()
    synced_staff = serializers.IntegerField()

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


class EnrollPrepareInput(serializers.Serializer):
    pin = serializers.CharField(required=False, allow_blank=True, max_length=16)


class EnrollPrepareOutput(serializers.Serializer):
    prepared = serializers.BooleanField()
    message = serializers.CharField()


class VaultSyncOutput(serializers.Serializer):
    stored = serializers.IntegerField(required=False)
    pushed = serializers.BooleanField(required=False)
    template_count = serializers.IntegerField(required=False)
    fingerprint_status = serializers.CharField(required=False)


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

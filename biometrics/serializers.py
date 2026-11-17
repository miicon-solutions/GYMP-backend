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

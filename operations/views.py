from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response

from accounts.identifiers import strip_member_id_prefix
from accounts.models import User
from biometrics import services as bio
from core.api import StaffPermission, SuperOnly
from core.endpoints import query_parameters
from operations import services
from operations.models import Activity, Cost, Holiday
from operations.serializers import (
    ActivitySerializer,
    CostSerializer,
    DeviceControllerInput,
    DeviceControllerOutput,
    DeviceControllersOutput,
    HolidaySerializer,
    StaffInput,
    StaffSerializer,
)


def _method_permissions(mapping):
    """Build get_permissions using feature.action codes (or SuperOnly)."""

    def get_permissions(self):
        entry = mapping.get(self.request.method)
        if entry is SuperOnly:
            return [SuperOnly()]
        if entry is None:
            return [SuperOnly()]
        return [StaffPermission(entry)()]

    return get_permissions


class StaffList(generics.ListCreateAPIView):
    serializer_class = StaffSerializer
    queryset = User.objects.filter(role="admin").select_related("staff_profile")
    get_permissions = _method_permissions({"GET": "staff.view", "POST": SuperOnly})

    @extend_schema(request=StaffInput, responses={201: StaffSerializer})
    def post(self, request, *args, **kwargs):
        services.require_admin(request.user, True)
        data = StaffInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            StaffSerializer(services.save_staff(request.user, data.validated_data)).data, status=201
        )


class StaffDetail(generics.GenericAPIView):
    permission_classes = [SuperOnly]
    serializer_class = StaffSerializer
    queryset = User.objects.filter(role="admin")

    @extend_schema(request=StaffInput)
    def patch(self, request, *args, **kwargs):
        data = StaffInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            StaffSerializer(
                services.save_staff(request.user, data.validated_data, self.get_object())
            ).data
        )

    def delete(self, request, *args, **kwargs):
        services.delete_staff(request.user, self.get_object())
        return Response(status=204)


class CostQuery(serializers.Serializer):
    include_archived = serializers.BooleanField(default=False)


class CostList(generics.ListCreateAPIView):
    serializer_class = CostSerializer
    get_permissions = _method_permissions({"GET": "costs.view", "POST": "costs.create"})

    @extend_schema(parameters=query_parameters("include_archived"))
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    def get_queryset(self):
        query = CostQuery(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return (
            Cost.objects.all()
            if query.validated_data["include_archived"]
            else Cost.objects.filter(is_archived=False)
        )

    def perform_create(self, serializer):
        serializer.instance = services.save_cost(self.request.user, serializer.validated_data)


class CostDetail(generics.GenericAPIView):
    serializer_class = CostSerializer
    queryset = Cost.objects.all()
    get_permissions = _method_permissions(
        {"GET": "costs.view", "PATCH": "costs.update", "DELETE": "costs.delete"}
    )

    def patch(self, request, *args, **kwargs):
        data = CostSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            CostSerializer(
                services.save_cost(request.user, data.validated_data, self.get_object())
            ).data
        )

    def delete(self, request, *args, **kwargs):
        services.mutate_cost(request.user, self.get_object(), "delete")
        return Response(status=204)


class ActivityQuery(serializers.Serializer):
    q = serializers.CharField(required=False, max_length=200, allow_blank=True)
    area = serializers.ChoiceField(
        choices=["member", "plan", "cost", "staff", "gym"], required=False
    )
    action = serializers.ChoiceField(
        choices=["create", "update", "delete", "activate", "deactivate", "archive"], required=False
    )
    admin_id = serializers.UUIDField(required=False)
    sort = serializers.ChoiceField(choices=["newest", "oldest"], default="newest")
    from_date = serializers.DateTimeField(required=False, input_formats=["iso-8601", "%Y-%m-%d"])
    to = serializers.DateTimeField(required=False, input_formats=["iso-8601", "%Y-%m-%d"])

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = fields.pop("from_date")
        return fields


class ActivityList(generics.ListAPIView):
    permission_classes = [StaffPermission("activity.view")]
    serializer_class = ActivitySerializer

    @extend_schema(
        parameters=query_parameters("q", "area", "action", "admin_id", "sort", "from", "to")
    )
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    def get_queryset(self):
        data = ActivityQuery(data=self.request.query_params)
        data.is_valid(raise_exception=True)
        filters = data.validated_data
        rows = Activity.objects.all()
        for key in ("area", "action", "admin_id"):
            if key in filters:
                rows = rows.filter(**{key: filters[key]})
        if filters.get("q"):
            q = filters["q"]
            member_q = strip_member_id_prefix(q)
            query = (
                Q(admin_name__icontains=q)
                | Q(admin_short_id__icontains=q)
                | Q(summary_key__icontains=q)
                | Q(summary_params__icontains=q)
            )
            if member_q != q:
                query |= Q(summary_params__icontains=member_q)
            rows = rows.filter(query)
        for field, lookup in (("from", "created_at__gte"), ("to", "created_at__lte")):
            if field in filters:
                rows = rows.filter(**{lookup: filters[field]})
        self.paginator.ordering = (
            ("created_at", "id") if filters["sort"] == "oldest" else ("-created_at", "-id")
        )
        return rows


class HolidayList(generics.ListCreateAPIView):
    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()
    get_permissions = _method_permissions(
        {"GET": "gym_hours.view", "POST": "gym_hours.create"}
    )

    def perform_create(self, serializer):
        serializer.instance = services.save_holiday(self.request.user, serializer.validated_data)


class HolidayDetail(generics.GenericAPIView):
    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()
    get_permissions = _method_permissions(
        {
            "GET": "gym_hours.view",
            "PATCH": "gym_hours.update",
            "DELETE": "gym_hours.delete",
        }
    )

    def patch(self, request, *args, **kwargs):
        data = HolidaySerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            HolidaySerializer(
                services.save_holiday(request.user, data.validated_data, self.get_object())
            ).data
        )

    def delete(self, request, *args, **kwargs):
        services.delete_holiday(request.user, self.get_object())
        return Response(status=204)


def staff_by_id(pk):
    return get_object_or_404(User, pk=pk, role="admin")


class DeviceControllersList(generics.GenericAPIView):
    """List/add staff who hold ZK device-admin privilege (permission-gated)."""

    get_permissions = _method_permissions(
        {"GET": "device_controllers.view", "POST": "device_controllers.create"}
    )

    @extend_schema(responses={200: DeviceControllersOutput})
    def get(self, request, *args, **kwargs):
        return Response(bio.list_device_controllers())

    @extend_schema(request=DeviceControllerInput, responses={200: DeviceControllerOutput})
    def post(self, request, *args, **kwargs):
        data = DeviceControllerInput(data=request.data)
        data.is_valid(raise_exception=True)
        staff = bio.device_controller_input_staff(data.validated_data["staff_id"])
        return Response(bio.add_device_controller(request.user, staff))

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response

from core.api import MemberOnly, StaffPermission
from members import services
from members.models import MemberProfile
from members.serializers import AdminMemberOutput, ProfileInput, ProfileOutput


class ProfileView(generics.GenericAPIView):
    permission_classes = [MemberOnly]
    serializer_class = ProfileInput

    @extend_schema(responses=ProfileOutput)
    def get(self, request):
        return Response(services.profile_data(request.user))

    @extend_schema(request=ProfileInput, responses=ProfileOutput)
    def put(self, request):
        data = ProfileInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(services.save_profile(request.user, data.validated_data))


class AdminMemberSerializer(AdminMemberOutput):
    def to_representation(self, obj):
        return services.admin_member_data(obj)


class MemberSearch(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=200)
    status = serializers.ChoiceField(choices=["unpaid", "active", "expired"], required=False)


class AdminMemberList(generics.ListAPIView):
    permission_classes = [StaffPermission("members.view")]
    serializer_class = AdminMemberSerializer

    @extend_schema(parameters=[MemberSearch])
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    def get_queryset(self):
        data = MemberSearch(data=self.request.query_params)
        data.is_valid(raise_exception=True)
        q = data.validated_data.get("q", "")
        rows = MemberProfile.objects.select_related("user", "plan").filter(
            Q(member_id__icontains=q)
            | Q(user__full_name__icontains=q)
            | Q(user__phone_e164__icontains=q)
        )
        status = data.validated_data.get("status")
        if status == "unpaid":
            return rows.filter(membership_status__in=["none", "pending_payment"])
        return rows.filter(membership_status=status) if status else rows


class AdminMemberDetail(generics.GenericAPIView):
    permission_classes = [StaffPermission("members.view")]
    serializer_class = AdminMemberSerializer

    def get(self, request, pk):
        return Response(services.admin_member_data(services.get_member(pk)))


class PhotoView(generics.GenericAPIView):
    from rest_framework.parsers import FormParser, MultiPartParser

    from members.serializers import PhotoInput

    permission_classes = [MemberOnly]
    serializer_class = PhotoInput
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses=ProfileOutput)
    def post(self, request):
        data = self.get_serializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(services.upload_photo(request.user, data.validated_data["photo"]))

    def delete(self, request):
        services.delete_photo(request.user)
        return Response(status=204)

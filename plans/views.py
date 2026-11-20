from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api import MemberOnly, StaffPermission
from plans import services
from plans.models import Offer, Plan
from plans.serializers import OfferInput, OfferSerializer, PlanInput, PlanSerializer


def _plan_method_permissions(mapping):
    def get_permissions(self):
        code = mapping.get(self.request.method, "plans.view")
        return [StaffPermission(code)()]

    return get_permissions


class PlanList(generics.ListCreateAPIView):
    serializer_class = PlanSerializer
    get_permissions = _plan_method_permissions({"GET": "plans.view", "POST": "plans.create"})

    def get_queryset(self):
        services.expire_offers()
        return Plan.objects.all()

    @extend_schema(request=PlanInput, responses={201: PlanSerializer})
    def create(self, request, *args, **kwargs):
        data = PlanInput(data=request.data)
        data.is_valid(raise_exception=True)
        obj = services.save_plan(request.user, data.validated_data)
        return Response(PlanSerializer(obj).data, status=201)


class PlanDetail(generics.GenericAPIView):
    serializer_class = PlanSerializer
    queryset = Plan.objects.all()
    get_permissions = _plan_method_permissions(
        {"GET": "plans.view", "PATCH": "plans.update", "DELETE": "plans.delete"}
    )

    @extend_schema(request=PlanInput, responses=PlanSerializer)
    def patch(self, request, *args, **kwargs):
        data = PlanInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        obj = services.save_plan(request.user, data.validated_data, self.get_object())
        return Response(PlanSerializer(obj).data)

    def delete(self, request, *args, **kwargs):
        services.delete_plan(request.user, self.get_object())
        return Response(status=204)


class MemberPlanList(generics.ListAPIView):
    permission_classes = [MemberOnly]
    serializer_class = PlanSerializer

    def get_queryset(self):
        services.expire_offers()
        return Plan.objects.filter(is_active=True)


class PublicPlanList(MemberPlanList):
    """The published catalogue contains pricing only, never member data."""

    permission_classes = [AllowAny]
    authentication_classes = []


class MemberPlanDetail(generics.RetrieveAPIView):
    permission_classes = [MemberOnly]
    serializer_class = PlanSerializer

    def get_queryset(self):
        services.expire_offers()
        return Plan.objects.filter(is_active=True)


class OfferList(generics.ListCreateAPIView):
    serializer_class = OfferSerializer
    get_permissions = _plan_method_permissions({"GET": "plans.view", "POST": "plans.create"})

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Offer.objects.none()
        services.expire_offers()
        return Offer.objects.filter(plan=get_object_or_404(Plan, pk=self.kwargs["pk"]))

    def create(self, request, *args, **kwargs):
        data = OfferInput(data=request.data)
        data.is_valid(raise_exception=True)
        obj = services.save_offer(
            request.user, get_object_or_404(Plan, pk=kwargs["pk"]), data.validated_data
        )
        return Response(OfferSerializer(obj).data, status=201)


class OfferDetail(generics.GenericAPIView):
    serializer_class = OfferSerializer
    get_permissions = _plan_method_permissions(
        {"GET": "plans.view", "PATCH": "plans.update", "DELETE": "plans.delete"}
    )

    def get_object(self):
        return get_object_or_404(Offer, pk=self.kwargs["offer_id"], plan_id=self.kwargs["pk"])

    def patch(self, request, *args, **kwargs):
        obj = self.get_object()
        data = OfferInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            OfferSerializer(
                services.save_offer(request.user, obj.plan, data.validated_data, obj)
            ).data
        )

    def delete(self, request, *args, **kwargs):
        services.delete_offer(request.user, self.get_object())
        return Response(status=204)

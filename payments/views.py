from django.conf import settings
from django.shortcuts import get_object_or_404, render
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied

from core.api import MemberOnly
from members.services import owned_profile
from payments.models import Payment
from payments.serializers import PaymentSerializer


class PaymentList(generics.ListAPIView):
    permission_classes = [MemberOnly]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(member=owned_profile(self.request.user))


class PaymentDetail(generics.RetrieveAPIView):
    permission_classes = [MemberOnly]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(member=owned_profile(self.request.user))


def receipt(request, data, pk, html=False):
    payment = get_object_or_404(Payment, pk=pk, member=owned_profile(request.user))
    if payment.status != "paid":
        raise PermissionDenied("Receipt is only available for paid payments.")
    if html:
        return render(request, "receipt.html", {"payment": payment, "member": payment.member})
    return {"url": f"{settings.PUBLIC_BASE_URL}/api/v1/member/payments/{payment.pk}/receipt.html/"}

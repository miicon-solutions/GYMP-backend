from datetime import datetime, time

from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import Conflict, require_admin
from operations.services import DHAKA, record
from plans.models import Offer, Plan


def discount(period, kind, value):
    if kind == "percent":
        return period * min(value, 100) // 100
    return min(period, value) if kind == "amount" else 0


def active_offer(plan, day=None):
    day = day or timezone.localdate()
    return plan.offers.filter(is_active=True, starts_on__lte=day, ends_on__gte=day).first()


def redeemed_count(offer):
    """Paid first payments that count toward this offer's first-N limit."""
    from payments.models import Payment

    paid_first = Payment.objects.filter(status="paid", is_first_payment=True)
    scope = offer.limit_scope or "offer"
    if scope == "offer":
        return paid_first.filter(offer_id=offer.pk).count()
    start = datetime.combine(offer.starts_on, time.min, tzinfo=DHAKA)
    paid_first = paid_first.filter(paid_at__gte=start)
    if scope == "plan":
        return paid_first.filter(plan_id=offer.plan_id).count()
    return paid_first.count()


def remaining_redemptions(offer):
    if offer.max_redemptions is None:
        return None
    return max(0, offer.max_redemptions - redeemed_count(offer))


def offer_admission_waived(offer):
    if not offer or not offer.waive_admission:
        return False
    remaining = remaining_redemptions(offer)
    return remaining is None or remaining > 0


def serialize_offer(offer):
    if offer is None:
        return None
    remaining = remaining_redemptions(offer)
    redeemed = redeemed_count(offer) if offer.max_redemptions is not None else None
    return {
        "id": str(offer.pk),
        "plan_id": str(offer.plan_id),
        "name": offer.name,
        "starts_on": offer.starts_on.isoformat(),
        "ends_on": offer.ends_on.isoformat(),
        "waive_admission": offer.waive_admission,
        "extra_discount_type": offer.extra_discount_type,
        "extra_discount_value": offer.extra_discount_value,
        "max_redemptions": offer.max_redemptions,
        "limit_scope": offer.limit_scope,
        "is_active": offer.is_active,
        "redeemed_count": redeemed,
        "remaining": remaining,
        "admission_waived": offer_admission_waived(offer),
    }


def pricing(plan, day=None):
    period = plan.monthly_rate_taka * plan.duration_months
    offer = active_offer(plan, day)
    standing = discount(period, plan.discount_type, plan.discount_value)
    offer_extra = (
        discount(period, offer.extra_discount_type, offer.extra_discount_value) if offer else 0
    )
    # Standing first, then offer against remainder so components sum to list − net.
    standing_applied = min(standing, period)
    offer_applied = min(offer_extra, period - standing_applied)
    renewal = period - standing_applied - offer_applied
    admission_list = plan.admission_fee_taka
    waived = bool(offer_admission_waived(offer))
    admission = 0 if waived else admission_list
    return {
        "period_coverage_taka": period,
        "renewal_taka": period,
        "effective_renewal_taka": renewal,
        "effective_first_payment_taka": renewal + admission,
        "first_payment_taka": renewal + admission,
        "standing_discount_taka": standing_applied,
        "offer_discount_taka": offer_applied,
        "admission_fee_taka": admission_list,
        "admission_waived": waived,
    }


def expire_offers():
    Offer.objects.filter(is_active=True, ends_on__lt=timezone.localdate()).update(is_active=False)


def validate_plan(data):
    period = data["monthly_rate_taka"] * data["duration_months"]
    if data["discount_type"] == "percent" and data["discount_value"] > 100:
        raise ValidationError({"discount_value": "Maximum is 100."})
    if data["discount_type"] == "amount" and data["discount_value"] > period:
        raise ValidationError({"discount_value": "Discount exceeds the period price."})


def validate_offer(values):
    if values["ends_on"] < values["starts_on"]:
        raise ValidationError({"ends_on": "Must be on or after the start date."})
    if values["extra_discount_type"] == "percent" and values["extra_discount_value"] > 100:
        raise ValidationError({"extra_discount_value": "Maximum is 100."})
    max_redemptions = values.get("max_redemptions")
    if max_redemptions is not None and max_redemptions < 1:
        raise ValidationError({"max_redemptions": "Must be at least 1."})
    limit_scope = values.get("limit_scope") or "offer"
    if limit_scope not in {"offer", "plan", "gym"}:
        raise ValidationError({"limit_scope": "Choose offer, plan, or gym."})


@transaction.atomic
def save_plan(actor, data, instance=None):
    require_admin(actor)
    if instance:
        instance = Plan.objects.select_for_update().get(pk=instance.pk)
    values = {field: getattr(instance, field) for field in data} if instance else {}
    if instance:
        values = {f.name: getattr(instance, f.name) for f in Plan._meta.fields}
    values.update(data)
    validate_plan(values)
    if (
        Plan.objects.filter(duration_months=values["duration_months"])
        .exclude(pk=getattr(instance, "pk", None))
        .exists()
    ):
        raise Conflict("A plan with this duration already exists.")
    before = instance.is_active if instance else None
    if instance:
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
    else:
        instance = Plan.objects.create(**data)
    action = "create" if before is None else "update"
    if before is not None and before != instance.is_active:
        action = "activate" if instance.is_active else "deactivate"
    record(
        actor,
        "plan",
        action,
        "adminActivityPlan"
        + {
            "create": "Created",
            "update": "Updated",
            "activate": "Activated",
            "deactivate": "Deactivated",
        }[action],
        {"name": instance.name},
    )
    return instance


@transaction.atomic
def delete_plan(actor, instance):
    require_admin(actor)
    instance = Plan.objects.select_for_update().get(pk=instance.pk)
    if instance.catalog_id:
        instance.is_active = False
        instance.save()
        action, key = "deactivate", "adminActivityPlanDeactivated"
    else:
        try:
            instance.delete()
        except ProtectedError as exc:
            raise Conflict(
                "This plan has payment or membership history. Deactivate it instead."
            ) from exc
        action, key = "delete", "adminActivityPlanDeleted"
    record(actor, "plan", action, key, {"name": instance.name})


@transaction.atomic
def save_offer(actor, plan, data, instance=None):
    require_admin(actor)
    Plan.objects.select_for_update().get(pk=plan.pk)  # Serialize overlap checks.
    if instance:
        instance = Offer.objects.select_for_update().get(pk=instance.pk, plan=plan)
    values = {f.name: getattr(instance, f.name) for f in Offer._meta.fields} if instance else {}
    values.update(data)
    validate_offer(values)
    if (
        values["is_active"]
        and Offer.objects.filter(
            plan=plan,
            is_active=True,
            starts_on__lte=values["ends_on"],
            ends_on__gte=values["starts_on"],
        )
        .exclude(pk=getattr(instance, "pk", None))
        .exists()
    ):
        raise Conflict("This offer overlaps another active offer.")
    created = instance is None
    if instance:
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
    else:
        instance = Offer.objects.create(plan=plan, **data)
    record(
        actor,
        "plan",
        "create" if created else "update",
        "adminActivityPlanOfferCreated" if created else "adminActivityPlanOfferUpdated",
        {"name": instance.name},
    )
    return instance


@transaction.atomic
def delete_offer(actor, instance):
    require_admin(actor)
    instance.delete()
    record(actor, "plan", "delete", "adminActivityPlanOfferDeleted", {"name": instance.name})

from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.api import Conflict, require_admin
from operations.services import record
from plans.models import Offer, Plan


def discount(period, kind, value):
    if kind == "percent":
        return period * min(value, 100) // 100
    return min(period, value) if kind == "amount" else 0


def active_offer(plan, day=None):
    day = day or timezone.localdate()
    return plan.offers.filter(is_active=True, starts_on__lte=day, ends_on__gte=day).first()


def pricing(plan, day=None):
    period = plan.monthly_rate_taka * plan.duration_months
    offer = active_offer(plan, day)
    reduction = discount(period, plan.discount_type, plan.discount_value)
    if offer:
        reduction += discount(period, offer.extra_discount_type, offer.extra_discount_value)
    renewal = max(0, period - reduction)
    admission = 0 if offer and offer.waive_admission else plan.admission_fee_taka
    return {
        "period_coverage_taka": period,
        "renewal_taka": period,
        "effective_renewal_taka": renewal,
        "effective_first_payment_taka": renewal + admission,
        "first_payment_taka": renewal + admission,
    }


def expire_offers():
    Offer.objects.filter(is_active=True, ends_on__lt=timezone.localdate()).update(is_active=False)


def validate_plan(data):
    period = data["monthly_rate_taka"] * data["duration_months"]
    if data["discount_type"] == "percent" and data["discount_value"] > 100:
        raise ValidationError({"discount_value": "Maximum is 100."})
    if data["discount_type"] == "amount" and data["discount_value"] > period:
        raise ValidationError({"discount_value": "Discount exceeds the period price."})


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
    if values["ends_on"] < values["starts_on"]:
        raise ValidationError({"ends_on": "Must be on or after the start date."})
    if values["extra_discount_type"] == "percent" and values["extra_discount_value"] > 100:
        raise ValidationError({"extra_discount_value": "Maximum is 100."})
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

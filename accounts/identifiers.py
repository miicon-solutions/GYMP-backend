from django.db import transaction


@transaction.atomic
def next_display(kind):
    from accounts.models import DisplaySequence
    from accounts.services import lock_key

    lock_key("display:" + kind)
    sequence, _ = DisplaySequence.objects.get_or_create(
        name=kind, defaults={"value": 1000 if kind == "staff" else 0}
    )
    sequence.value += 1
    sequence.save(update_fields=["value"])
    return f"ADM-{sequence.value:04d}" if kind == "staff" else f"PG-{sequence.value:04d}"

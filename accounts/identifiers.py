from django.db import transaction

MEMBER_ID_WIDTH = 9
TEMPORARY_MEMBER_PREFIX = "PFT-"
TEMPORARY_MEMBER_WIDTH = 6


def is_temporary_member_id(value: str) -> bool:
    body = (value or "")[len(TEMPORARY_MEMBER_PREFIX) :]
    return (
        (value or "").startswith(TEMPORARY_MEMBER_PREFIX)
        and len(body) == TEMPORARY_MEMBER_WIDTH
        and body.isdigit()
    )


def strip_member_id_prefix(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned[:3].upper() == "PG-" and cleaned[3:].isdigit():
        return cleaned[3:]
    return cleaned


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
    if kind == "staff":
        return f"ADM-{sequence.value:04d}"
    if kind == "member_temporary":
        return f"{TEMPORARY_MEMBER_PREFIX}{sequence.value:0{TEMPORARY_MEMBER_WIDTH}d}"
    return f"{sequence.value:0{MEMBER_ID_WIDTH}d}"

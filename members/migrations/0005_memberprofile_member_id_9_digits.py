import re

from django.db import migrations, models

_PREFIXED_DIGITS = re.compile(r"^(?:PG|PF)-(\d+)$", re.IGNORECASE)


def _normalize(value: str) -> str:
    raw = (value or "").strip()
    match = _PREFIXED_DIGITS.match(raw)
    digits = match.group(1) if match else raw
    if digits.isdigit():
        return digits.zfill(9)[-9:]
    return raw[:9]


def strip_member_id_prefix_in_db(apps, schema_editor):
    MemberProfile = apps.get_model("members", "MemberProfile")
    existing = set(MemberProfile.objects.values_list("member_id", flat=True))
    for profile in MemberProfile.objects.all().order_by("created_at", "id"):
        target = _normalize(profile.member_id)
        if target == profile.member_id:
            continue
        if target in existing:
            continue
        existing.discard(profile.member_id)
        existing.add(target)
        profile.member_id = target
        profile.save(update_fields=["member_id"])

    Activity = apps.get_model("operations", "Activity")
    for activity in Activity.objects.all():
        params = activity.summary_params
        if not isinstance(params, dict):
            continue
        changed = False
        for key in ("member_id", "memberId"):
            val = params.get(key)
            if isinstance(val, str):
                normalized = _normalize(val)
                if normalized != val:
                    params[key] = normalized
                    changed = True
        if changed:
            activity.summary_params = params
            activity.save(update_fields=["summary_params"])


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0004_memberprofile_age_memberprofile_height_cm_and_more"),
        ("operations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(strip_member_id_prefix_in_db, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="memberprofile",
            name="member_id",
            field=models.CharField(max_length=9, unique=True),
        ),
    ]

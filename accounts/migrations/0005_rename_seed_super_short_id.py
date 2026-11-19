from django.db import migrations


LEGACY = ("S-ADM-7400", "S-ADM-740")
CANONICAL = "SADM-7400"


def forwards(apps, schema_editor):
    StaffProfile = apps.get_model("accounts", "StaffProfile")
    if StaffProfile.objects.filter(short_id=CANONICAL).exists():
        # Canonical already present — drop legacy duplicates if any.
        StaffProfile.objects.filter(short_id__in=LEGACY).delete()
        return
    StaffProfile.objects.filter(short_id__in=LEGACY).update(short_id=CANONICAL)


def backwards(apps, schema_editor):
    StaffProfile = apps.get_model("accounts", "StaffProfile")
    StaffProfile.objects.filter(short_id=CANONICAL).update(short_id="S-ADM-7400")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_staff_fingerprint_device_admin"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

from django.db import migrations


def forwards(apps, schema_editor):
    MemberProfile = apps.get_model("members", "MemberProfile")
    for profile in MemberProfile.objects.filter(member_id__startswith="PG-").iterator():
        profile.member_id = "PF-" + profile.member_id[3:]
        profile.save(update_fields=["member_id"])


def backwards(apps, schema_editor):
    MemberProfile = apps.get_model("members", "MemberProfile")
    for profile in MemberProfile.objects.filter(member_id__startswith="PF-").iterator():
        profile.member_id = "PG-" + profile.member_id[3:]
        profile.save(update_fields=["member_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0004_user_delete_cascade"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

from django.db import migrations, models


def set_require_approval_true(apps, schema_editor):
    MusicSettings = apps.get_model("music", "MusicSettings")
    MusicSettings.objects.filter(singleton_id=1).update(require_approval=True)


class Migration(migrations.Migration):
    dependencies = [
        ("music", "0002_musicqueueitem_approved_by_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="musicsettings",
            name="require_approval",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(set_require_approval_true, migrations.RunPython.noop),
    ]

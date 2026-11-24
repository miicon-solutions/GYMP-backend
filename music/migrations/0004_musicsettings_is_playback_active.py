from django.db import migrations, models


def activate_if_currently_playing(apps, schema_editor):
    MusicSettings = apps.get_model("music", "MusicSettings")
    MusicQueueItem = apps.get_model("music", "MusicQueueItem")
    if MusicQueueItem.objects.filter(status="playing", is_reported=False).exists():
        MusicSettings.objects.filter(singleton_id=1).update(is_playback_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("music", "0003_musicsettings_require_approval_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="musicsettings",
            name="is_playback_active",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(activate_if_currently_playing, migrations.RunPython.noop),
    ]

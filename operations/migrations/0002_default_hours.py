from datetime import time

from django.db import migrations


def seed_hours(apps, schema_editor):
    Weekday = apps.get_model("operations", "WeekdayHours")
    for day in range(1, 8):
        Weekday.objects.get_or_create(
            weekday=day,
            defaults={
                "is_open": day != 5,
                "open_time": time(6) if day != 5 else None,
                "close_time": time(22) if day != 5 else None,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]
    operations = [migrations.RunPython(seed_hours, migrations.RunPython.noop)]

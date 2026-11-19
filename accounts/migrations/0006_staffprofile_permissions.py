from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_rename_seed_super_short_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffprofile",
            name="permissions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]

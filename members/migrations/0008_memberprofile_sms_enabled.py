from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0007_notifications_and_push_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberprofile",
            name="sms_enabled",
            field=models.BooleanField(default=True),
        ),
    ]

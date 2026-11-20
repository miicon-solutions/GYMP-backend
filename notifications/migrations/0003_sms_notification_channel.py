from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_staff_announcement"),
    ]

    operations = [
        migrations.AddField(
            model_name="membernotification",
            name="send_sms",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="staffannouncement",
            name="send_sms_requested",
            field=models.BooleanField(default=False),
        ),
    ]

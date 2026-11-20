from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0003_sms_notification_channel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="membernotification",
            name="code",
            field=models.CharField(
                choices=[
                    ("payment_received", "payment_received"),
                    ("cash_request", "cash_request"),
                    ("cash_request_rejected", "cash_request_rejected"),
                    ("membership_activated", "membership_activated"),
                    ("fingerprint_ready", "fingerprint_ready"),
                    ("membership_expiring", "membership_expiring"),
                    ("membership_expired", "membership_expired"),
                    ("announcement", "announcement"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]

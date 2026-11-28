from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0006_music_request_notification_codes"),
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
                    ("cash_request_accepted", "cash_request_accepted"),
                    ("cash_request_staff_rejected", "cash_request_staff_rejected"),
                    ("membership_activated", "membership_activated"),
                    ("fingerprint_ready", "fingerprint_ready"),
                    ("membership_expiring", "membership_expiring"),
                    ("membership_expired", "membership_expired"),
                    ("announcement", "announcement"),
                    ("admin_enrollment", "admin_enrollment"),
                    ("admin_daily_enrollments", "admin_daily_enrollments"),
                    ("music_request", "music_request"),
                    ("music_request_approved", "music_request_approved"),
                    ("music_request_rejected", "music_request_rejected"),
                    ("music_request_staff_approved", "music_request_staff_approved"),
                    ("music_request_staff_rejected", "music_request_staff_rejected"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]

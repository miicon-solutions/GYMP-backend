from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_device_keypad_and_staff_pin"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="preferred_language",
            field=models.CharField(
                choices=[("bn", "Bangla"), ("en", "English")],
                default="bn",
                max_length=2,
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("preferred_language__in", ["bn", "en"])),
                name="valid_preferred_language",
            ),
        ),
    ]

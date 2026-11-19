from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0003_checkin_auto_closed_checkin_check_out_source_and_more"),
        ("attendance", "0003_user_delete_cascade"),
    ]

    operations = []

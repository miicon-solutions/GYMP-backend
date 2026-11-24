from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0010_merge_20261125_0430"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memberprofile",
            name="member_id",
            field=models.CharField(max_length=10, unique=True),
        ),
    ]

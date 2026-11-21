# Generated manually for discount comparison reports

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0005_offer_first_n_redemptions"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="list_amount_taka",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="standing_discount_taka",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="offer_discount_taka",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="admission_waived_taka",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]

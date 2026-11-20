import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0001_notifications_and_push_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffAnnouncement",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=120)),
                ("body", models.TextField()),
                (
                    "scope",
                    models.CharField(
                        choices=[("member", "member"), ("active", "active")], max_length=16
                    ),
                ),
                ("member_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("send_push_requested", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staff_announcements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="staffannouncement",
            index=models.Index(fields=["-created_at"], name="staff_announce_created_idx"),
        ),
    ]

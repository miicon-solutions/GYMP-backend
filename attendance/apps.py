from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendance"
    verbose_name = "Attendance"

    def ready(self) -> None:
        from attendance.bridge_pull import maybe_start_from_apps

        maybe_start_from_apps()

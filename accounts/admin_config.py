from django.contrib.admin.apps import AdminConfig


class OperatorAdminConfig(AdminConfig):
    default_site = "accounts.admin_site.OperatorAdminSite"

from django.contrib import admin


class OperatorModelAdmin(admin.ModelAdmin):
    """Operator console CRUD with system fields locked and secrets kept out of forms."""

    _system_readonly = ("id", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        declared = list(super().get_readonly_fields(request, obj))
        model_fields = {f.name for f in self.model._meta.get_fields() if hasattr(f, "attname")}
        for name in self._system_readonly:
            if name in model_fields and name not in declared:
                declared.append(name)
        if obj is None:
            return [f for f in declared if f != "updated_at"]
        return declared


# Back-compat alias for older imports / docs.
ReadOnlyAdmin = OperatorModelAdmin

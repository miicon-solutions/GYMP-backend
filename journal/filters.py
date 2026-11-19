import django_filters

from journal.models import GymJournalEntry


class JournalFilter(django_filters.FilterSet):
    tag = django_filters.CharFilter(method="filter_by_tag")
    date_from = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = GymJournalEntry
        fields = ["tag", "energy_level", "muscle_soreness", "sleep_quality", "cns_drive"]

    def filter_by_tag(self, queryset, name, value):
        if not value:
            return queryset
        tag = value.strip()
        if not tag.startswith("#"):
            tag = f"#{tag}"
        return queryset.filter(tags__icontains=tag)

import django_filters

from nutrition.models import Recipe


class RecipeFilter(django_filters.FilterSet):
    tag = django_filters.CharFilter(method="filter_by_tag")
    is_predefined = django_filters.BooleanFilter()

    class Meta:
        model = Recipe
        fields = ["is_predefined"]

    def filter_by_tag(self, queryset, name, value):
        if not value:
            return queryset
        # Search JSON tags array
        return queryset.filter(tags__icontains=value.strip())

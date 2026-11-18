from django.urls import path

from schedules.views import ActiveCycleDayView, ActiveCycleView, AutoPopulateCycleView

urlpatterns = [
    path("active-cycle/", ActiveCycleView.as_view(), name="active-cycle"),
    path(
        "active-cycle/days/<int:day_index>/",
        ActiveCycleDayView.as_view(),
        name="active-cycle-day",
    ),
    path(
        "active-cycle/auto-populate/",
        AutoPopulateCycleView.as_view(),
        name="active-cycle-auto-populate",
    ),
]

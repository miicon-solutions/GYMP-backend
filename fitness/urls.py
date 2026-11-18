from django.urls import path

from fitness.views import AnthropometryView, UserProfileView

urlpatterns = [
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("anthropometry/", AnthropometryView.as_view(), name="user-anthropometry"),
]

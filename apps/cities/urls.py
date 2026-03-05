from django.urls import path

from apps.cities.views import list_cities


urlpatterns = [
    path("list/", list_cities, name="city-list"),
]


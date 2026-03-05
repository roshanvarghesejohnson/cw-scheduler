from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.cities.models import City


@api_view(["GET"])
def list_cities(request):
    """
    Return all active cities for use by frontend booking forms.

    Only exposes the fields required by the frontend (id and name) and
    filters to cities marked as is_active=True so new cities added in the
    Django admin automatically appear once activated.
    """
    cities = City.objects.filter(is_active=True).order_by("name").values("id", "name")
    return Response(list(cities))


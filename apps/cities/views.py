from logging import getLogger

from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.cities.models import City


logger = getLogger(__name__)


@api_view(["GET"])
def list_cities(request):
    """
    Return all active cities for use by frontend booking forms.

    Only exposes the fields required by the frontend (id and name) and
    filters to cities marked as is_active=True so new cities added in the
    Django admin automatically appear once activated.
    """
    cities_qs = City.objects.filter(is_active=True).order_by("name").values(
        "id", "name"
    )
    cities = list(cities_qs)
    logger.debug("list_cities called | count=%s", len(cities))
    return Response(cities)


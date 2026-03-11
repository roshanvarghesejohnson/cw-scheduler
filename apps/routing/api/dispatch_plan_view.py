"""
Read-only API endpoint for dispatch plans.

Returns technician routes and summary metrics for a given city and date.
"""

from __future__ import annotations

from datetime import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cities.models import City
from apps.routing.services.dispatch_dashboard_service import DispatchDashboardService


class DispatchPlanView(APIView):
    """
    GET: Return dispatch plan (technician routes + metrics) for a city and date.

    Query params:
        city: required, city name
        date: required, YYYY-MM-DD
    """

    def get(self, request):
        city_name = request.query_params.get("city")
        date_str = request.query_params.get("date")

        if not city_name:
            return Response(
                {"detail": "Missing required parameter: city"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not date_str:
            return Response(
                {"detail": "Missing required parameter: date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            city = City.objects.get(name=city_name)
        except City.DoesNotExist:
            return Response(
                {"detail": f"City '{city_name}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        service = DispatchDashboardService()
        payload = service.get_dispatch_plan(city=city, service_date=service_date)
        return Response(payload, status=status.HTTP_200_OK)


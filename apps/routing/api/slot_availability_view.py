"""
Read-only API endpoint for available slots.

Used by customer-facing booking forms (e.g. Zoho Sites) to display available
time windows. Technician assignment is handled later by the scheduling engine
after booking creation.
"""

from __future__ import annotations

from datetime import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cities.models import City
from apps.routing.services.slot_availability_service import SlotAvailabilityService


class SlotAvailabilityView(APIView):
    """
    GET: Return available slots for a city and date.

    Query params: city (required), date (YYYY-MM-DD, required).
    Returns 200 with list of { slot_id, start_time, end_time, remaining_capacity }.
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

        service = SlotAvailabilityService()
        slots = service.get_available_slots(city=city, service_date=service_date)

        # Serialize time fields for JSON response.
        out = []
        for s in slots:
            start = s["start_time"]
            end = s["end_time"]
            out.append({
                "slot_id": s["slot_id"],
                "start_time": start.isoformat() if hasattr(start, "isoformat") else str(start),
                "end_time": end.isoformat() if hasattr(end, "isoformat") else str(end),
                "remaining_capacity": s["remaining_capacity"],
            })

        return Response(out, status=status.HTTP_200_OK)

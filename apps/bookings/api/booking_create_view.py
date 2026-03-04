"""
Booking creation API for the CycleWorks Scheduling System.

Main entry point for customer bookings from external forms (e.g. Zoho Sites).
Creates the booking with the selected slot and triggers the scheduling engine
(slot assignment for any unassigned bookings, then technician assignment).
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from apps.cities.models import City
from apps.customers.models import Customer
from apps.routing.services.scheduling_service import SchedulingService
from apps.routing.services.technician_assignment_service import (
    TechnicianAssignmentService,
)
from apps.slots.models import Slot


REQUIRED_FIELDS = ("name", "phone", "address", "city", "slot_id", "service_date")


class BookingCreateView(APIView):
    """
    POST: Create a booking with selected slot and run the scheduling pipeline.

    Accepts JSON with customer details and slot_id; reuses or creates Customer,
    creates Booking, then runs slot + technician assignment for that city/date.
    """

    def post(self, request):
        data = request.data if hasattr(request, "data") else {}

        for field in REQUIRED_FIELDS:
            if not data.get(field):
                return Response(
                    {"detail": f"Missing required field: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        city_name = data["city"]
        date_str = data["service_date"]
        slot_id = data["slot_id"]

        try:
            service_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
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

        try:
            slot = Slot.objects.get(pk=slot_id, city=city, date=service_date)
        except Slot.DoesNotExist:
            return Response(
                {"detail": "Slot not found or does not match city/date."},
                status=status.HTTP_404_NOT_FOUND,
            )

        remaining = slot.max_capacity - slot.current_utilization
        if remaining <= 0:
            return Response(
                {"detail": "Selected slot has no remaining capacity."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer = Customer.objects.filter(
            phone=data["phone"],
            city=city,
        ).first()
        if customer is None:
            customer = Customer.objects.create(
                name=data["name"],
                phone=data["phone"],
                email=data.get("email") or None,
                address=data["address"],
                city=city,
                cycle_brand=data.get("cycle_brand") or None,
                cycle_model=data.get("cycle_model") or None,
            )

        with transaction.atomic():
            booking = Booking.objects.create(
                customer=customer,
                city=city,
                slot=slot,
                service_date=service_date,
                status=Booking.Status.REQUESTED,
                technician=None,
            )
            slot.current_utilization += 1
            slot.save(update_fields=["current_utilization"])

            SchedulingService().auto_assign_slots(
                city=city, service_date=service_date
            )
            TechnicianAssignmentService().auto_assign_technicians(
                city=city, service_date=service_date
            )
            booking.refresh_from_db()

        return Response(
            {
                "booking_id": booking.id,
                "status": booking.status,
                "slot_id": slot.id,
            },
            status=status.HTTP_201_CREATED,
        )

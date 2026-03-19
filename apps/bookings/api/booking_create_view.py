"""
Booking creation API for the CycleWorks Scheduling System.

Main entry point for customer bookings from external forms (e.g. Zoho Sites).
Creates the booking with the selected slot, geocodes the address, and updates
slot utilization. Technician assignment is performed by the dispatch optimizer
(run_dispatch / run_next_day_dispatch), not during booking creation.
"""

from __future__ import annotations

from datetime import datetime

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from apps.customers.models import Customer
from apps.integrations.services.zoho_crm_service import ZohoCRMService
from apps.routing.services.geocoding_service import GeocodingService
from apps.slots.models import Slot


REQUIRED_FIELDS = ("slot_id", "phone", "address")


logger = logging.getLogger(__name__)


class BookingCreateView(APIView):
    """
    POST: Create a booking with selected slot.

    Accepts JSON with customer details and slot_id; reuses or creates Customer,
    creates Booking, increments slot utilization, and geocodes the address.
    Technician assignment is performed by the dispatch optimizer, not here.
    """

    def post(self, request):
        data = request.data if hasattr(request, "data") else {}

        # Support both the original payload shape and the simplified one:
        # - original: name, phone, address, city, slot_id, service_date
        # - simplified (Zoho): customer_name, phone, address, slot_id, bike_type

        # Basic required fields common to both shapes.
        for field in REQUIRED_FIELDS:
            if not data.get(field):
                return Response(
                    {"success": False, "message": f"Missing required field: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Canonical fields
        slot_id = data.get("slot_id")
        name = data.get("name") or data.get("customer_name")
        phone = data.get("phone")
        address = data.get("address")
        bike_type = data.get("bike_type")
        email = data.get("email")
        cycle_brand = data.get("cycle_brand") or bike_type
        cycle_model = data.get("cycle_model")

        if not name:
            return Response(
                {"success": False, "message": "Missing required field: name"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optional hints; if provided, they must match the slot we resolve below.
        provided_city_name = data.get("city")
        provided_date_str = data.get("service_date")

        # Resolve slot and infer city/service_date from it.
        try:
            slot = Slot.objects.select_related("city").get(pk=slot_id)
        except Slot.DoesNotExist:
            return Response(
                {"success": False, "message": "Slot not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        city = slot.city
        service_date = slot.date

        if provided_date_str:
            try:
                parsed_date = datetime.strptime(provided_date_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return Response(
                    {"success": False, "message": "Invalid date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if parsed_date != service_date:
                return Response(
                    {
                        "success": False,
                        "message": "Provided service_date does not match slot date.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if provided_city_name and provided_city_name != city.name:
            return Response(
                {
                    "success": False,
                    "message": "Provided city does not match slot city.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        remaining = slot.max_capacity - slot.current_utilization
        if remaining <= 0:
            return Response(
                {"success": False, "message": "Selected slot is fully booked"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer = Customer.objects.filter(
            phone=phone,
            city=city,
        ).first()
        if customer is None:
            customer = Customer.objects.create(
                name=name,
                phone=phone,
                email=email or None,
                address=address,
                city=city,
                cycle_brand=cycle_brand or None,
                cycle_model=cycle_model or None,
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

        # Geocode address (outside transaction to avoid holding lock during HTTP)
        coords = GeocodingService().geocode_address(address, city.name) if address else None
        if coords:
            booking.latitude, booking.longitude = coords
            booking.save(update_fields=["latitude", "longitude"])

        # Create Zoho CRM Deal for this booking. This is best-effort: any errors
        # are logged and do not affect the booking confirmation response.
        try:
            crm_service = ZohoCRMService()
            deal_id = crm_service.create_deal(booking)
            if deal_id:
                booking.crm_deal_id = deal_id
                booking.save(update_fields=["crm_deal_id"])
        except Exception:
            logger.exception("Zoho deal creation failed")

        return Response(
            {
                "success": True,
                "message": "Booking confirmed",
                "booking_id": booking.id,
                "status": booking.status,
                "slot_id": slot.id,
            },
            status=status.HTTP_201_CREATED,
        )

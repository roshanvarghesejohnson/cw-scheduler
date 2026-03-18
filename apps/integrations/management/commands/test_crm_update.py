from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.bookings.models import Booking
from apps.integrations.services.zoho_crm_service import ZohoCRMService


class Command(BaseCommand):
    """
    Send a test Zoho CRM update for a given deal_id.

    Usage:
        python manage.py test_crm_update --deal_id <deal_id>
    """

    help = "Send a test Zoho CRM update for a given deal_id."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--deal_id",
            required=True,
            help="Zoho CRM Deal ID to test.",
        )

    def handle(self, *args, **options) -> None:
        deal_id = options["deal_id"]
        crm = ZohoCRMService()

        # Try to find an existing booking with this crm_deal_id to use real data.
        booking = (
            Booking.objects.filter(crm_deal_id=deal_id)
            .select_related("customer", "city", "slot", "technician")
            .first()
        )

        if not booking:
            # Create a lightweight dummy booking object in memory to carry fields.
            self.stdout.write(
                self.style.WARNING(
                    "No Booking found with this crm_deal_id; "
                    "sending minimal test payload using synthetic data."
                )
            )

            class DummyBooking:
                id = None
                city = None
                customer = None

            booking = DummyBooking()  # type: ignore[assignment]
            technician_name = "Test Technician"
            service_date = date.today()
            slot_start = None
            slot_end = None
        else:
            technician_name = (
                booking.technician.name if booking.technician else "Unassigned"
            )
            service_date = booking.service_date
            slot_start = booking.slot.start_time if booking.slot else None
            slot_end = booking.slot.end_time if booking.slot else None

        try:
            crm.update_deal_assignment(
                deal_id,
                technician_name,
                service_date,
                slot_start,
                slot_end,
                booking,
            )
        except Exception as exc:
            raise CommandError(f"CRM update failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Test CRM update sent for deal {deal_id}"))


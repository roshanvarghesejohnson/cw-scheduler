"""
Primary daily scheduling entrypoint for the CycleWorks Scheduling Engine.

This orchestration command runs the full scheduling pipeline:

1. auto_assign_slots   – Assigns REQUESTED bookings to available slots
2. auto_assign_technicians – Assigns technicians to slot-assigned bookings

Ops run this daily instead of invoking the individual commands manually. Future
geo-routing logic will be plugged into the technician assignment stage.
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.cities.models import City
from apps.routing.services.scheduling_service import SchedulingService
from apps.routing.services.technician_assignment_service import (
    TechnicianAssignmentService,
)


class Command(BaseCommand):
    """
    Run the full scheduling pipeline for a city and date.

    Orchestrates slot assignment followed by technician assignment. This is the
    primary daily entrypoint for ops; future geo-routing will replace the
    technician selection logic within the pipeline.
    """

    help = "Run full scheduling pipeline (slots + technicians) for a city and date."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--city",
            required=True,
            help="Name of the city as stored in the City model.",
        )
        parser.add_argument(
            "--date",
            required=True,
            help="Service date in YYYY-MM-DD format.",
        )

    def handle(self, *args, **options) -> None:
        city_name = options["city"]
        date_str = options["date"]

        try:
            service_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Invalid date format. Expected YYYY-MM-DD.") from exc

        try:
            city = City.objects.get(name=city_name)
        except City.DoesNotExist as exc:
            raise CommandError(f"City '{city_name}' does not exist.") from exc

        slot_service = SchedulingService()
        tech_service = TechnicianAssignmentService()

        slots_assigned = slot_service.auto_assign_slots(
            city=city, service_date=service_date
        )
        techs_assigned = tech_service.auto_assign_technicians(
            city=city, service_date=service_date
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduling complete: {slots_assigned} bookings assigned to slots, "
                f"{techs_assigned} bookings assigned to technicians."
            )
        )

"""
Management command to run the dispatch optimizer for a city and date.

Usage:
    python manage.py run_dispatch --city Mumbai --date 2026-03-07

Runs:
1. Slot assignment (for any unassigned REQUESTED bookings)
2. Dispatch optimization (assigns technicians, route ordering)
3. Generates and prints dispatch plan
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.cities.models import City
from apps.routing.services.dispatch_optimizer_service import DispatchOptimizerService
from apps.routing.services.dispatch_service import generate_dispatch_plan
from apps.routing.services.scheduling_service import SchedulingService


class Command(BaseCommand):
    help = (
        "Run dispatch optimizer for a city and date: slot assignment, "
        "technician assignment via optimization, then print routes."
    )

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
        slots_assigned = slot_service.auto_assign_slots(
            city=city, service_date=service_date
        )
        self.stdout.write(f"Slots assigned: {slots_assigned}")

        optimizer = DispatchOptimizerService()
        techs_assigned = optimizer.optimize(city=city, service_date=service_date)
        self.stdout.write(self.style.SUCCESS(f"Technicians assigned: {techs_assigned}"))

        plan = generate_dispatch_plan(city=city, service_date=service_date)
        self.stdout.write("")
        self.stdout.write("=== Dispatch Plan ===")
        for tech_id, bookings in plan.items():
            tech = bookings[0].technician if bookings else None
            tech_name = tech.name if tech else f"Tech #{tech_id}"
            self.stdout.write(f"\n{tech_name}:")
            for b in bookings:
                slot_str = f"{b.slot.start_time}-{b.slot.end_time}" if b.slot else "?"
                pos = b.route_position or "?"
                self.stdout.write(
                    f"  {pos}. Booking #{b.pk} | {b.customer.name} | {slot_str}"
                )

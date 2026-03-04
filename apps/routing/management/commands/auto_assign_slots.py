"""
Management command to run the v1 scheduling engine.

Usage example:
    python manage.py auto_assign_slots --city "Mumbai" --date 2026-03-01
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.cities.models import City
from apps.routing.services.scheduling_service import SchedulingService


class Command(BaseCommand):
    """
    Automatically assign unassigned REQUESTED bookings to available slots for a
    given city and service date.

    This is a thin wrapper around SchedulingService.auto_assign_slots and is
    intended for operational use (e.g., running via cron or manually by ops).
    """

    help = "Auto-assign REQUESTED bookings to available slots for a city and date."

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
            raise CommandError(f"City with name '{city_name}' does not exist.") from exc

        service = SchedulingService()
        assigned_count = service.auto_assign_slots(city=city, service_date=service_date)

        self.stdout.write(
            self.style.SUCCESS(f"Assigned {assigned_count} bookings to slots.")
        )


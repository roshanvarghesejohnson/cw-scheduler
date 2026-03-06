"""
Management command to run dispatch for all active cities for tomorrow.

Usage:
    python manage.py run_next_day_dispatch

Steps:
1. tomorrow = IST date + 1
2. For each active city: run optimizer, generate dispatch plan
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from zoneinfo import ZoneInfo

from apps.cities.models import City
from apps.routing.services.dispatch_optimizer_service import DispatchOptimizerService
from apps.routing.services.dispatch_service import generate_dispatch_plan
from apps.routing.services.scheduling_service import SchedulingService

IST = ZoneInfo("Asia/Kolkata")


class Command(BaseCommand):
    help = (
        "Run dispatch optimizer for tomorrow for all active cities. "
        "Slot assignment + technician assignment via optimization."
    )

    def handle(self, *args, **options) -> None:
        now_ist = timezone.now().astimezone(IST)
        tomorrow = now_ist.date() + timedelta(days=1)
        self.stdout.write(f"Running dispatch for {tomorrow} (IST)")

        cities = City.objects.filter(is_active=True).order_by("name")
        slot_service = SchedulingService()
        optimizer = DispatchOptimizerService()

        total_slots = 0
        total_techs = 0

        for city in cities:
            slots_assigned = slot_service.auto_assign_slots(
                city=city, service_date=tomorrow
            )
            techs_assigned = optimizer.optimize(city=city, service_date=tomorrow)
            total_slots += slots_assigned
            total_techs += techs_assigned

            plan = generate_dispatch_plan(city=city, service_date=tomorrow)
            if plan:
                self.stdout.write(f"\n--- {city.name} ---")
                for tech_id, bookings in plan.items():
                    tech = bookings[0].technician if bookings else None
                    tech_name = tech.name if tech else f"Tech #{tech_id}"
                    self.stdout.write(f"  {tech_name}: {len(bookings)} bookings")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Slots assigned: {total_slots}, technicians assigned: {total_techs}"
            )
        )

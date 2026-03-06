"""
Management command to generate synthetic bookings for development and testing.

WARNING: This command generates synthetic bookings for testing.
Use only in development environments.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bookings.models import Booking
from apps.cities.models import City
from apps.customers.models import Customer
from apps.routing.services.dispatch_optimizer_service import DispatchOptimizerService
from apps.slots.models import Slot

# City bounding boxes (lat_min, lat_max, lon_min, lon_max) for synthetic coordinates.
CITY_BOUNDS: Dict[str, Tuple[float, float, float, float]] = {
    "Mumbai": (18.90, 19.30, 72.75, 72.98),
    "Bangalore": (12.85, 13.15, 77.45, 77.75),
    "Hyderabad": (17.20, 17.60, 78.30, 78.60),
    "Pune": (18.40, 18.70, 73.70, 74.00),
}
DEFAULT_BOUNDS = (18.90, 19.30, 72.75, 72.98)  # Mumbai-like fallback


def _bounds_for_city(city_name: str) -> Tuple[float, float, float, float]:
    """Return (lat_min, lat_max, lon_min, lon_max) for a city."""
    return CITY_BOUNDS.get(city_name, DEFAULT_BOUNDS)


def _random_coords_in_city(city_name: str, rng: random.Random) -> Tuple[float, float]:
    """Generate random (lat, lon) within city bounds."""
    lat_min, lat_max, lon_min, lon_max = _bounds_for_city(city_name)
    lat = rng.uniform(lat_min, lat_max)
    lon = rng.uniform(lon_min, lon_max)
    return (lat, lon)


class Command(BaseCommand):
    help = (
        "Generate synthetic bookings for a city/date for development and testing. "
        "Distributes bookings across slots with remaining capacity. "
        "Use --run-dispatch to run the dispatch optimizer after generation."
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
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="Number of bookings to create (default: 50).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Random seed for reproducibility.",
        )
        parser.add_argument(
            "--run-dispatch",
            action="store_true",
            help="Run DispatchOptimizerService after generating bookings.",
        )

    def handle(self, *args, **options) -> None:
        self.stdout.write(
            self.style.WARNING(
                "WARNING: This command generates synthetic bookings for testing."
            )
        )

        city_name = options["city"]
        date_str = options["date"]
        count = options["count"]
        seed: Optional[int] = options["seed"]
        run_dispatch = options["run_dispatch"]

        try:
            service_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Invalid date format. Expected YYYY-MM-DD.") from exc

        try:
            city = City.objects.get(name=city_name)
        except City.DoesNotExist as exc:
            raise CommandError(f"City '{city_name}' does not exist.") from exc

        slots = list(
            Slot.objects.filter(city=city, date=service_date).order_by("start_time")
        )
        if not slots:
            self.stdout.write(
                self.style.ERROR(
                    "No slots found for city/date. Run generate_slots first."
                )
            )
            return

        if count < 1:
            raise CommandError("--count must be at least 1.")

        rng = random.Random(seed)

        slots_with_capacity: List[Slot] = []
        for slot in slots:
            remaining = slot.max_capacity - slot.current_utilization
            if remaining > 0:
                slots_with_capacity.append(slot)

        if not slots_with_capacity:
            self.stdout.write(
                self.style.ERROR(
                    "All slots are full for this city/date. No bookings created."
                )
            )
            return

        created = 0
        slots_used: Dict[int, int] = defaultdict(int)

        with transaction.atomic():
            for i in range(count):
                slots_with_capacity = [
                    s for s in slots
                    if s.max_capacity - s.current_utilization > 0
                ]
                if not slots_with_capacity:
                    self.stdout.write(
                        self.style.WARNING(
                            f"All slots full after {created} bookings."
                        )
                    )
                    break

                slot = rng.choice(slots_with_capacity)

                lat, lon = _random_coords_in_city(city.name, rng)
                phone = str(9000000000 + i)
                name = f"Test Customer {i + 1}"
                address = f"Random Street {i + 1}, {city.name}"

                customer = Customer.objects.create(
                    name=name,
                    phone=phone,
                    address=address,
                    city=city,
                    latitude=lat,
                    longitude=lon,
                )

                Booking.objects.create(
                    customer=customer,
                    city=city,
                    slot=slot,
                    service_date=service_date,
                    latitude=lat,
                    longitude=lon,
                    status=Booking.Status.REQUESTED,
                    technician=None,
                )
                slot.current_utilization += 1
                slot.save(update_fields=["current_utilization"])
                slots_used[slot.id] += 1
                created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Created {created} bookings across {len(slots_used)} slots")
        )
        if created < count:
            self.stdout.write(
                f"Stopped early: all slots full (requested {count}, created {created})."
            )

        if run_dispatch:
            self.stdout.write("Running dispatch optimizer...")
            optimizer = DispatchOptimizerService()
            assigned = optimizer.optimize(city=city, service_date=service_date)
            self.stdout.write(
                self.style.SUCCESS(f"Assigned technicians to {assigned} bookings.")
            )

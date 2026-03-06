"""
Automatic slot generation service for CycleWorks.

This service generates fixed 2-hour service windows for the next 7 days for
each active city. Slot capacity is derived from the number of active and
available technicians in the city. It is designed to be triggered daily via a
management command (e.g. from a cron job) and does not modify any existing
booking or routing APIs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time, timedelta
from typing import Dict, List

from django.utils import timezone
from zoneinfo import ZoneInfo

from apps.cities.models import City
from apps.slots.models import Slot
from apps.technicians.models import Technician

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


SLOT_WINDOWS: List[tuple[time, time]] = [
    (time(9, 0), time(11, 0)),
    (time(11, 0), time(13, 0)),
    (time(13, 0), time(15, 0)),
    (time(15, 0), time(17, 0)),
]


@dataclass
class SlotGenerationSummary:
    cities_processed: int
    slots_created: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "cities_processed": self.cities_processed,
            "slots_created": self.slots_created,
        }


def generate_slots_for_next_7_days() -> Dict[str, int]:
    """
    Generate service slots for the next 7 days for all active cities.

    - Uses timezone-aware dates relative to Asia/Kolkata.
    - For each active city, calculates capacity based on active+available
      technicians.
    - Skips slots that already exist for a given (city, date, start_time).
    - Uses bulk_create for efficiency.

    Returns:
        dict: {"cities_processed": N, "slots_created": M}
    """
    # Determine "today" in Asia/Kolkata so that the next 7 days are computed
    # relative to the India service window rather than server local time.
    now_ist = timezone.now().astimezone(IST)
    today = now_ist.date()
    dates = [today + timedelta(days=offset) for offset in range(1, 8)]

    cities = City.objects.filter(is_active=True).order_by("name")
    total_slots_created = 0

    for city in cities:
        created_for_city = generate_slots_for_city(city, dates)
        total_slots_created += created_for_city
        logger.info(
            "Slot generation | city=%s slots_created=%s",
            city.name,
            created_for_city,
        )

    summary = SlotGenerationSummary(
        cities_processed=cities.count(),
        slots_created=total_slots_created,
    )
    logger.info(
        "Slot generation summary | cities_processed=%s slots_created=%s",
        summary.cities_processed,
        summary.slots_created,
    )
    return summary.as_dict()


def generate_slots_for_city(city: City, dates: List[timezone.datetime.date]) -> int:
    """
    Generate slots for a single city across the given list of dates.

    Capacity per slot = active_and_available_technicians (one job per technician
    per slot window). If no technicians are available in the city, no slots are
    created.
    """
    tech_count = (
        Technician.objects.filter(
            city=city,
            is_active=True,
            is_available=True,
        ).count()
    )

    if tech_count <= 0:
        logger.info("No active/available technicians for city=%s; skipping", city.name)
        return 0

    capacity_per_slot = tech_count

    # Fetch existing slots once to avoid per-slot queries.
    existing_pairs = set(
        Slot.objects.filter(city=city, date__in=dates).values_list(
            "date", "start_time"
        )
    )

    to_create: List[Slot] = []

    for date in dates:
        for start_time, end_time in SLOT_WINDOWS:
            key = (date, start_time)
            if key in existing_pairs:
                continue
            to_create.append(
                Slot(
                    city=city,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    max_capacity=capacity_per_slot,
                    current_utilization=0,
                )
            )

    if not to_create:
        return 0

    Slot.objects.bulk_create(to_create)
    return len(to_create)


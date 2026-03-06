"""
Dispatch service for the CycleWorks Scheduling Engine.

Generates dispatch plans (technician → ordered bookings) for a city and date.
Used after optimization to produce human-readable route output.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from apps.bookings.models import Booking
from apps.cities.models import City


def generate_dispatch_plan(city: City, service_date) -> Dict[int, List[Booking]]:
    """
    Generate dispatch plan: technician_id -> list of bookings in route order.

    Returns dict mapping technician pk to list of Booking instances ordered by
    route_position (or slot/created_at if route_position not set).
    """
    bookings = (
        Booking.objects.filter(
            city=city,
            service_date=service_date,
            technician__isnull=False,
            slot__isnull=False,
        )
        .select_related("technician", "slot", "customer")
        .order_by("technician_id", "route_position", "slot__start_time", "created_at")
    )

    plan: Dict[int, List[Booking]] = defaultdict(list)
    for b in bookings:
        plan[b.technician_id].append(b)

    return dict(plan)

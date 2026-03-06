"""
Dispatch optimizer for the CycleWorks Scheduling Engine.

Performs route optimization before technician assignment. Assigns bookings to
technicians using greedy distance minimization, then orders each technician's
route using nearest-neighbor. Technician assignment is committed only after
optimization completes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from django.db import transaction

from apps.bookings.models import Booking
from apps.routing.services.distance_service import DistanceService
from apps.technicians.models import Technician

logger = logging.getLogger(__name__)


def _booking_coords(booking: Booking) -> Optional[Tuple[float, float]]:
    """Return (lat, lon) for a booking; prefer booking coords, fallback to customer."""
    if booking.latitude is not None and booking.longitude is not None:
        return (booking.latitude, booking.longitude)
    if booking.customer_id and hasattr(booking, "customer"):
        c = booking.customer
        if c.latitude is not None and c.longitude is not None:
            return (c.latitude, c.longitude)
    return None


def _nearest_neighbor_route(
    distance_service: DistanceService,
    origin_lat: Optional[float],
    origin_lon: Optional[float],
    bookings: List[Booking],
) -> List[Booking]:
    """
    Order bookings by nearest-neighbor from origin.
    Returns ordered list; skips bookings with no coordinates.
    """
    if not bookings:
        return []
    if origin_lat is None or origin_lon is None:
        return list(bookings)  # No reordering possible

    remaining = list(bookings)
    ordered: List[Booking] = []
    curr_lat, curr_lon = origin_lat, origin_lon

    while remaining:
        best_dist = float("inf")
        best_idx = -1
        for i, b in enumerate(remaining):
            coords = _booking_coords(b)
            if coords is None:
                continue
            d = distance_service.distance_km(curr_lat, curr_lon, coords[0], coords[1])
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_idx < 0:
            break
        chosen = remaining.pop(best_idx)
        ordered.append(chosen)
        coords = _booking_coords(chosen)
        if coords:
            curr_lat, curr_lon = coords

    return ordered


class DispatchOptimizerService:
    """
    Optimizes technician assignment and route ordering.

    Algorithm:
    1. Fetch unassigned bookings (has slot, no technician) and available technicians.
    2. Build distance matrix; use greedy assignment respecting daily_capacity and
       per-slot exclusivity.
    3. For each technician, order their bookings by nearest-neighbor from base.
    4. Commit assignments (technician, status, route_position).
    """

    @transaction.atomic
    def optimize(self, city, service_date) -> int:
        """
        Run optimization and commit technician assignments.

        Returns the number of bookings assigned to technicians.
        """
        bookings = list(
            Booking.objects.select_for_update()
            .filter(
                city=city,
                service_date=service_date,
                status=Booking.Status.REQUESTED,
                slot__isnull=False,
                technician__isnull=True,
            )
            .select_related("slot", "customer")
            .order_by("slot__start_time", "created_at", "pk")
        )

        technicians = list(
            Technician.objects.select_for_update()
            .filter(city=city, is_active=True, is_available=True)
            .order_by("pk")
        )

        if not technicians or not bookings:
            return 0

        distance_service = DistanceService()

        tech_daily_counts: Dict[int, int] = {
            t.pk: Booking.objects.filter(
                technician=t, service_date=service_date
            ).count()
            for t in technicians
        }

        existing_pairs = Booking.objects.filter(
            city=city,
            service_date=service_date,
            technician__isnull=False,
            slot__isnull=False,
        ).values_list("technician_id", "slot_id")
        tech_slot_usage: Set[Tuple[int, int]] = set(existing_pairs)

        tech_by_pk = {t.pk: t for t in technicians}

        assignments: Dict[int, List[Booking]] = defaultdict(list)

        for booking in bookings:
            coords = _booking_coords(booking)
            if coords is None:
                logger.warning(
                    "Skipping booking %s: no coordinates (booking or customer)",
                    booking.pk,
                )
                continue

            best_tech = None
            best_dist = float("inf")

            for tech in technicians:
                if tech_daily_counts[tech.pk] >= tech.daily_capacity:
                    continue
                if (tech.pk, booking.slot_id) in tech_slot_usage:
                    continue

                d = distance_service.distance_km(
                    tech.base_latitude,
                    tech.base_longitude,
                    coords[0],
                    coords[1],
                )
                if d != float("inf") and d < best_dist:
                    best_dist = d
                    best_tech = tech

            if best_tech is None:
                continue

            assignments[best_tech.pk].append(booking)
            tech_daily_counts[best_tech.pk] += 1
            tech_slot_usage.add((best_tech.pk, booking.slot_id))

        to_update: List[Booking] = []

        for tech_pk, tech_bookings in assignments.items():
            tech = tech_by_pk[tech_pk]
            ordered = _nearest_neighbor_route(
                distance_service,
                tech.base_latitude,
                tech.base_longitude,
                tech_bookings,
            )
            for pos, b in enumerate(ordered, start=1):
                b.technician_id = tech_pk
                b.status = Booking.Status.CONFIRMED
                b.route_position = pos
                to_update.append(b)

        if to_update:
            Booking.objects.bulk_update(
                to_update, ["technician", "status", "route_position"]
            )

        return len(to_update)

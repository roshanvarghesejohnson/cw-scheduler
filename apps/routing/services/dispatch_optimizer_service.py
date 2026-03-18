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
from apps.integrations.services.zoho_crm_service import ZohoCRMService
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


class DispatchOptimizerService:
    """
    Optimizes technician assignment and route ordering using route-aware greedy
    optimization.

    Algorithm:
    1. Fetch unassigned bookings (has slot, no technician) and available technicians.
    2. Maintain in-memory route state per technician:
       {tech_id: {current_lat, current_lon, bookings: [...]}}.
    3. For each booking (in slot/time order), choose the technician whose current
       route end is closest to the booking, respecting daily_capacity and per-slot
       exclusivity.
    4. Append the booking to that technician's route and update current_lat/lon.
    5. Commit assignments (technician, status, route_position) based on the
       in-memory routes.
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

        # In-memory route state per technician.
        routes: Dict[int, Dict[str, object]] = {}
        for tech in technicians:
            routes[tech.pk] = {
                "current_lat": tech.base_latitude,
                "current_lon": tech.base_longitude,
                "bookings": [],  # type: List[Booking]
            }

        # Route-aware greedy assignment: process bookings in slot/time order,
        # always extending the nearest technician route that can still take
        # the booking.
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
                tech_id = tech.pk
                if tech_daily_counts[tech_id] >= tech.daily_capacity:
                    continue
                if (tech_id, booking.slot_id) in tech_slot_usage:
                    continue

                state = routes[tech_id]
                curr_lat = state["current_lat"]
                curr_lon = state["current_lon"]
                if curr_lat is None or curr_lon is None:
                    # No meaningful origin; skip tech until base coords are set.
                    continue

                d = distance_service.distance_km(
                    curr_lat,
                    curr_lon,
                    coords[0],
                    coords[1],
                )
                if d != float("inf") and d < best_dist:
                    best_dist = d
                    best_tech = tech

            if best_tech is None:
                continue

            tech_id = best_tech.pk
            state = routes[tech_id]
            # Append booking to this technician's in-memory route.
            state_bookings: List[Booking] = state["bookings"]  # type: ignore[assignment]
            state_bookings.append(booking)
            state["current_lat"], state["current_lon"] = coords

            tech_daily_counts[tech_id] += 1
            tech_slot_usage.add((tech_id, booking.slot_id))

        to_update: List[Booking] = []

        # Route order is the order in which bookings were appended to each
        # technician's in-memory route.
        for tech_pk, state in routes.items():
            tech_bookings: List[Booking] = state["bookings"]  # type: ignore[assignment]
            if not tech_bookings:
                continue
            for pos, b in enumerate(tech_bookings, start=1):
                b.technician_id = tech_pk
                b.status = Booking.Status.CONFIRMED
                b.route_position = pos
                to_update.append(b)

        if to_update:
            Booking.objects.bulk_update(
                to_update, ["technician", "status", "route_position"]
            )

            # After DB state is committed, trigger Zoho CRM sync.
            crm_service = ZohoCRMService()
            for b in to_update:
                if getattr(b, "crm_deal_id", None) and b.technician_id:
                    tech = next(
                        (t for t in technicians if t.pk == b.technician_id), None
                    )
                    if not tech:
                        continue
                    try:
                        crm_service.update_deal_assignment(
                            b.crm_deal_id,
                            tech.name,
                            b.service_date,
                            b.slot.start_time if b.slot else None,
                            b.slot.end_time if b.slot else None,
                            b,
                        )
                    except Exception:
                        logger.exception(
                            "Zoho CRM sync failed for booking %s", b.pk
                        )

        return len(to_update)

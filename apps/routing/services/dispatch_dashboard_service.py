"""
Dispatch dashboard service for CycleWorks.

Provides a read-only view of daily dispatch plans, grouped by technician with
route ordering and distance estimates for observability and debugging.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import time as dt_time
from typing import Dict, List, Optional, Tuple
from apps.bookings.models import Booking
from apps.cities.models import City
from apps.routing.services.distance_service import DistanceService
from apps.technicians.models import Technician


def _booking_coords(booking: Booking) -> Optional[Tuple[float, float]]:
    """
    Return (lat, lon) for a booking, preferring booking coords then customer.
    """
    if booking.latitude is not None and booking.longitude is not None:
        return (booking.latitude, booking.longitude)
    if booking.customer and booking.customer.latitude is not None and booking.customer.longitude is not None:
        return (booking.customer.latitude, booking.customer.longitude)
    return None


class DispatchDashboardService:
    """
    Read-only service to build dispatch plans for a city/date.
    """

    def __init__(self) -> None:
        self._distance_service = DistanceService()

    def get_dispatch_plan(self, city: City, service_date) -> Dict:
        """
        Build dispatch plan and summary for a city and service_date.
        """
        # All bookings for summary.
        all_qs = Booking.objects.filter(city=city, service_date=service_date)

        # Assigned bookings ordered primarily by route_position, with a
        # fallback to slot.start_time when route_position is null.
        assigned_qs = (
            all_qs.filter(technician__isnull=False, slot__isnull=False)
            .select_related("technician", "slot", "customer")
            .order_by("technician_id", "route_position", "slot__start_time")
        )

        total_bookings = all_qs.count()
        assigned_bookings = assigned_qs.count()
        unassigned_bookings = total_bookings - assigned_bookings

        # Group bookings by technician.
        tech_routes: Dict[int, List[Booking]] = defaultdict(list)
        techs: Dict[int, Technician] = {}
        for b in assigned_qs:
            tech_routes[b.technician_id].append(b)
            if b.technician_id not in techs:
                techs[b.technician_id] = b.technician

        technicians_used = len(tech_routes)
        average_jobs_per_technician = (
            float(assigned_bookings) / technicians_used if technicians_used > 0 else 0.0
        )

        technicians_payload: List[Dict] = []

        for tech_id, bookings in tech_routes.items():
            tech = techs[tech_id]
            jobs_payload: List[Dict] = []

            # Build jobs list and compute route distance.
            total_distance = 0.0
            curr_lat = tech.base_latitude
            curr_lon = tech.base_longitude

            # Ensure strict ordering: route_position ASC, fallback to slot.start_time.
            bookings_sorted = sorted(
                bookings,
                key=lambda b: (
                    b.route_position is None,
                    b.route_position or 0,
                    b.slot.start_time if b.slot and b.slot.start_time else dt_time.min,
                ),
            )

            for b in bookings_sorted:
                coords = _booking_coords(b)
                jobs_payload.append(
                    {
                        "route_position": b.route_position,
                        "booking_id": b.id,
                        "customer_name": b.customer.name if b.customer else None,
                        "address": b.customer.address if b.customer else None,
                        "latitude": coords[0] if coords else None,
                        "longitude": coords[1] if coords else None,
                        "slot_start": (
                            b.slot.start_time.isoformat(timespec="minutes")
                            if b.slot and b.slot.start_time
                            else None
                        ),
                        "slot_end": (
                            b.slot.end_time.isoformat(timespec="minutes")
                            if b.slot and b.slot.end_time
                            else None
                        ),
                    }
                )

                if curr_lat is not None and curr_lon is not None and coords:
                    leg = self._distance_service.distance_km(
                        curr_lat, curr_lon, coords[0], coords[1]
                    )
                    if leg != float("inf"):
                        total_distance += leg
                if coords:
                    curr_lat, curr_lon = coords

            total_jobs = len(bookings_sorted)
            utilization = (
                float(total_jobs) / tech.daily_capacity if tech.daily_capacity > 0 else 0.0
            )

            technicians_payload.append(
                {
                    "technician_id": tech.id,
                    "technician_name": tech.name,
                    "base_latitude": tech.base_latitude,
                    "base_longitude": tech.base_longitude,
                    "jobs": jobs_payload,
                    "total_jobs": total_jobs,
                    "technician_utilization": utilization,
                    "estimated_route_distance_km": round(total_distance, 2),
                }
            )

        city_summary = {
            "total_bookings": total_bookings,
            "assigned_bookings": assigned_bookings,
            "unassigned_bookings": unassigned_bookings,
            "technicians_used": technicians_used,
            "average_jobs_per_technician": average_jobs_per_technician,
        }

        return {
            "city": city.name,
            "date": str(service_date),
            "city_summary": city_summary,
            "technicians": technicians_payload,
        }


"""
Slot availability service for the CycleWorks Scheduling System.

Provides a read-only view of which time windows still have capacity for a
given city and date. This service is the foundation for customer-facing slot
selection; technician routing and assignment are performed after booking
creation by the scheduling pipeline.
"""

from __future__ import annotations

from apps.slots.models import Slot


class SlotAvailabilityService:
    """
    Returns available (capacity remaining) slots for a city and date.

    Read-only; does not mutate database state. Used by customers or ops to
    see which time windows are still bookable before creating a booking.
    """

    def get_available_slots(self, city, service_date):
        """
        Return slots that still have capacity for the given city and date.

        Returns a list of dicts with slot_id, start_time, end_time, and
        remaining_capacity. Slots are ordered by start_time. Only slots
        with remaining_capacity > 0 are included. If no slots exist or none
        have capacity, returns an empty list.
        """
        slots = Slot.objects.filter(
            city=city,
            date=service_date,
        ).order_by("start_time", "pk")

        result = []
        for slot in slots:
            remaining_capacity = slot.max_capacity - slot.current_utilization
            if remaining_capacity <= 0:
                continue
            result.append({
                "slot_id": slot.id,
                "start_time": slot.start_time,
                "end_time": slot.end_time,
                "remaining_capacity": remaining_capacity,
            })
        return result

"""
Scheduling engine v1 for CycleWorks.

This module provides a minimal, deterministic scheduling routine that assigns
unassigned REQUESTED bookings to available city/date-specific slots while
respecting slot capacity limits. Technician assignment and route optimization
are explicitly out of scope for this version and will be layered on later.
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction

from apps.bookings.models import Booking
from apps.slots.models import Slot


class SchedulingService:
    """
    Encapsulates the core logic for automatically assigning bookings to slots.

    Slot capacity is strictly enforced: no slot may exceed max_capacity.
    Overbooking is impossible through this service; any violation (e.g. from
    logical bug or manual DB tampering) raises a hard ValueError.

    Assumptions for v1:
    - Only BOOKINGS with status=REQUESTED and slot is NULL are considered.
    - Only SLOTS for the same city and service_date are considered.
    - Technician assignment and routing are deferred to later stages.
    """

    @transaction.atomic
    def auto_assign_slots(self, city, service_date) -> int:
        """
        Auto-assign unassigned REQUESTED bookings to available slots.

        The algorithm:
        - Fetch all eligible bookings for the given city and service_date,
          ordered by created_at ascending (FIFO from operations' perspective).
        - Fetch all slots for the same city and date, ordered by start_time
          ascending.
        - Walk slots chronologically, filling each up to its remaining capacity
          (max_capacity - current_utilization) with the next bookings in line.
        - Slot capacity is strictly enforced; overbooking raises ValueError.
        - Slot.current_utilization is updated to reflect new assignments.

        This method intentionally does NOT:
        - Change booking status (it remains REQUESTED).
        - Assign technicians.

        Returns:
            int: The number of bookings that were assigned to slots.
        """

        # Lock relevant bookings and slots to avoid race conditions in
        # concurrent scheduling runs.
        bookings_qs = (
            Booking.objects.select_for_update()
            .filter(
                city=city,
                service_date=service_date,
                status=Booking.Status.REQUESTED,
                slot__isnull=True,
            )
            .order_by("created_at", "pk")
        )

        slots = list(
            Slot.objects.select_for_update()
            .filter(city=city, date=service_date)
            .order_by("start_time", "pk")
        )

        # Materialize bookings so we can iterate and slice easily.
        bookings = list(bookings_qs)
        if not bookings or not slots:
            return 0

        booking_index = 0
        total_assigned = 0
        updated_slots = set()

        for slot in slots:
            if booking_index >= len(bookings):
                break

            remaining_capacity = slot.max_capacity - slot.current_utilization
            if remaining_capacity <= 0:
                continue

            # Determine which bookings to assign into this slot. Defensive: never
            # assign more than remaining_capacity even if data was corrupted.
            to_assign = bookings[booking_index : booking_index + remaining_capacity]
            to_assign = to_assign[:remaining_capacity]
            if not to_assign:
                break

            for booking in to_assign:
                booking.slot = slot

            Booking.objects.bulk_update(to_assign, ["slot"])

            assigned_here = len(to_assign)
            slot.current_utilization += assigned_here

            # Final safety: catch logical bugs or manual DB tampering.
            if slot.current_utilization > slot.max_capacity:
                raise ValueError(
                    f"Slot capacity exceeded for slot {slot.id}: "
                    f"{slot.current_utilization}/{slot.max_capacity}"
                )

            updated_slots.add(slot)

            total_assigned += assigned_here
            booking_index += assigned_here

            if booking_index >= len(bookings):
                break

        if updated_slots:
            Slot.objects.bulk_update(list(updated_slots), ["current_utilization"])

        return total_assigned


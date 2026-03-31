"""
Phase 2: Automatic technician assignment for CycleWorks Scheduling Engine.

This module provides distance-based assignment with per-slot exclusivity and
daily capacity. Within each slot, a greedy global matching heuristic chooses
technician-booking pairs to minimize total cost (distance + continuity penalty)
across the slot. Technician location is updated after each assignment. It runs
independently after slot assignment and does not modify slot logic.

Future improvement: full route optimization per technician (e.g. TSP);
current logic approximates minimizing total city-wide travel more effectively
than pure sequential greedy.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from django.db import transaction

from apps.bookings.models import Booking
from apps.integrations.services.zoho_crm_service import (
    ZOHO_DEAL_STAGE_CUSTOMER_APPROVED,
    ZohoCRMService,
)
from apps.routing.services.distance_service import DistanceService
from apps.technicians.models import Technician

logger = logging.getLogger(__name__)

CONTINUITY_FACTOR = 0.15  # 15% penalty weight on leg distance (tunable)


class TechnicianAssignmentService:
    """
    Assigns technicians to bookings that have slots but no technician.

    Matching is performed per slot using a greedy global pairing heuristic:
    within each slot (processed in start_time order), the (technician, booking)
    pair with minimum final_cost is chosen repeatedly until no valid pairs
    remain. This approximates minimizing total city-wide travel more
    effectively than pure sequential greedy. Per-slot exclusivity and daily
    capacity are still enforced.
    """

    @transaction.atomic
    def auto_assign_technicians(self, city, service_date) -> int:
        """
        Auto-assign technicians using per-slot greedy global matching.

        Algorithm:
        - Fetch eligible bookings (REQUESTED, has slot, no technician) and
          active/available technicians. Preload existing usage and daily
          counts. Maintain tech_current_location (updated after each assign).
        - Group bookings by slot; process slots in start_time order.
        - For each slot: collect remaining bookings and eligible technicians
          (under capacity, not already in this slot). Repeatedly pick the
          (tech, booking) pair with minimum final_cost (distance + continuity
          penalty), assign them, remove that tech and booking from the slot
          pool, update state. Continue until no valid pairs or no finite costs.
        - Bulk update all assigned bookings at the end.

        Debug-level logs expose cost evaluations (distance, penalty, final) per
        (technician, booking) pair to aid tuning of CONTINUITY_FACTOR and
        future routing heuristics.
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

        # Daily assignment count per technician (existing + will assign).
        tech_daily_counts: Dict[int, int] = {
            tech.pk: Booking.objects.filter(
                technician=tech,
                service_date=service_date,
            ).count()
            for tech in technicians
        }

        # (tech_id, slot_id) pairs already used for this date.
        existing_pairs = Booking.objects.filter(
            city=city,
            service_date=service_date,
            technician__isnull=False,
            slot__isnull=False,
        ).values_list("technician_id", "slot_id")
        tech_slot_usage: Set[Tuple[int, int]] = set(existing_pairs)

        # Dynamic location per technician; starts at base, updated after each assign.
        tech_current_location: Dict[int, Tuple[float, float]] = {}
        for tech in technicians:
            tech_current_location[tech.pk] = (
                tech.base_latitude,
                tech.base_longitude,
            )

        # Preload current location from existing assignments (last assignment wins).
        existing_ordered = (
            Booking.objects.filter(
                city=city,
                service_date=service_date,
                technician__isnull=False,
            )
            .select_related("customer", "technician")
            .order_by("slot__start_time", "created_at")
        )
        for b in existing_ordered:
            tech_current_location[b.technician_id] = (
                b.customer.latitude,
                b.customer.longitude,
            )

        # Group bookings by slot; process slots in start_time order.
        bookings_by_slot: Dict[int, List[Booking]] = defaultdict(list)
        for b in bookings:
            bookings_by_slot[b.slot_id].append(b)
        ordered_slot_ids = sorted(
            bookings_by_slot.keys(),
            key=lambda sid: bookings_by_slot[sid][0].slot.start_time,
        )

        assigned = []
        for slot_id in ordered_slot_ids:
            remaining_bookings = list(bookings_by_slot[slot_id])
            available_techs = [
                t
                for t in technicians
                if tech_daily_counts[t.pk] < t.daily_capacity
                and (t.pk, slot_id) not in tech_slot_usage
            ]

            while remaining_bookings and available_techs:
                best_cost = float("inf")
                best_tech = None
                best_booking = None

                for tech in available_techs:
                    curr = tech_current_location[tech.pk]
                    for booking in remaining_bookings:
                        booking_loc = (
                            booking.customer.latitude,
                            booking.customer.longitude,
                        )
                        distance_cost = distance_service.distance_km(
                            curr[0], curr[1],
                            booking_loc[0], booking_loc[1],
                        )
                        if distance_cost == float("inf"):
                            continue
                        continuity_penalty = (
                            distance_cost * CONTINUITY_FACTOR
                            if tech_daily_counts[tech.pk] > 0
                            else 0.0
                        )
                        final_cost = distance_cost + continuity_penalty
                        logger.debug(
                            "Routing cost eval | slot=%s booking=%s tech=%s dist=%.3f penalty=%.3f final=%.3f",
                            slot_id,
                            booking.pk,
                            tech.pk,
                            distance_cost,
                            continuity_penalty,
                            final_cost,
                        )
                        if final_cost < best_cost:
                            best_cost = final_cost
                            best_tech = tech
                            best_booking = booking

                if best_tech is None or best_booking is None:
                    break

                best_booking.technician = best_tech
                best_booking.status = Booking.Status.CONFIRMED
                assigned.append(best_booking)
                logger.info(
                    "Routing assign | slot=%s booking=%s tech=%s final_cost=%.3f",
                    slot_id,
                    best_booking.pk,
                    best_tech.pk,
                    best_cost,
                )

                tech_daily_counts[best_tech.pk] += 1
                tech_slot_usage.add((best_tech.pk, slot_id))
                tech_current_location[best_tech.pk] = (
                    best_booking.customer.latitude,
                    best_booking.customer.longitude,
                )

                remaining_bookings.remove(best_booking)
                available_techs.remove(best_tech)

        if assigned:
            Booking.objects.bulk_update(assigned, ["technician", "status"])
            crm_service = ZohoCRMService()
            for b in assigned:
                if (
                    not getattr(b, "crm_deal_id", None)
                    or not b.technician_id
                    or b.status != Booking.Status.CONFIRMED
                ):
                    continue
                tech = b.technician
                print(
                    "Zoho: confirmed+technician booking",
                    b.pk,
                    "deal",
                    b.crm_deal_id,
                    "→ stage",
                    ZOHO_DEAL_STAGE_CUSTOMER_APPROVED,
                )
                try:
                    crm_service.update_deal(
                        b.crm_deal_id,
                        {"Stage": ZOHO_DEAL_STAGE_CUSTOMER_APPROVED},
                    )
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

        return len(assigned)

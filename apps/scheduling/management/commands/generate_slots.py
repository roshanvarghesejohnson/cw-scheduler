"""
Management command to run the automatic slot generation service.

Intended to be triggered daily at 20:00 server time (e.g. via cron or a
scheduled job on Render). On each run it generates slots for the next 7 days
for all active cities, skipping any slots that already exist.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.scheduling.services.slot_generation_service import (
    generate_slots_for_next_7_days,
)


class Command(BaseCommand):
    help = (
        "Generate service slots for the next 7 days for all active cities. "
        "Capacity per slot is based on the number of active and available "
        "technicians in each city."
    )

    def handle(self, *args, **options):
        summary = generate_slots_for_next_7_days()
        self.stdout.write(
            self.style.SUCCESS(
                f"Slot generation complete. Cities processed: "
                f"{summary['cities_processed']}, slots created: "
                f"{summary['slots_created']}."
            )
        )


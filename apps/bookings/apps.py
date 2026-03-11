from django.apps import AppConfig


class BookingsConfig(AppConfig):
    name = "apps.bookings"

    def ready(self) -> None:
        # Import signal handlers to keep Slot.current_utilization in sync with
        # Booking lifecycle events (delete, slot changes).
        import apps.bookings.signals  # noqa: F401


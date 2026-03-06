from django.db import models


class Booking(models.Model):
    """
    Central operational entity representing a customer's service request as it
    moves through the scheduling workflow. Technician and slot assignments are
    added progressively as planning decisions are made.
    """

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        CONFIRMED = "CONFIRMED", "Confirmed"
        RESOLUTION_REQUIRED = "RESOLUTION_REQUIRED", "Resolution required"
        RESCHEDULED = "RESCHEDULED", "Rescheduled"
        CANCELLED = "CANCELLED", "Cancelled"
        FORWARDED_TO_AGENCY = "FORWARDED_TO_AGENCY", "Forwarded to agency"

    class HandlingDecision(models.TextChoices):
        INTERNAL = "INTERNAL", "Internal"
        AGENCY = "AGENCY", "Agency"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="Customer who requested the service.",
    )
    city = models.ForeignKey(
        "cities.City",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text=(
            "Operational city context for this booking. Usually matches the "
            "customer's city, but stored explicitly for reporting and routing."
        ),
    )
    slot = models.ForeignKey(
        "slots.Slot",
        on_delete=models.PROTECT,
        related_name="bookings",
        null=True,
        blank=True,
        help_text=(
            "Tentative 2-hour slot for this booking once it enters the planning "
            "phase. May be null while still in early stages."
        ),
    )
    technician = models.ForeignKey(
        "technicians.Technician",
        on_delete=models.PROTECT,
        related_name="bookings",
        null=True,
        blank=True,
        help_text=(
            "Assigned technician for this booking once scheduling is finalized. "
            "May be null before assignment."
        ),
    )
    service_date = models.DateField(
        help_text="Target date on which service is planned to occur.",
    )
    handling_decision = models.CharField(
        max_length=20,
        choices=HandlingDecision.choices,
        null=True,
        blank=True,
        help_text=(
            "In hybrid cities, indicates whether this particular booking is "
            "handled by internal technicians or forwarded to an external agency."
        ),
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.REQUESTED,
        help_text="Current state of the booking in the scheduling workflow.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Operations notes, customer constraints, or exception details.",
    )
    latitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Service location latitude for routing; geocoded from address.",
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Service location longitude for routing; geocoded from address.",
    )
    route_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Stop order in technician's route (1-based); set by dispatch optimizer.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the booking was first created.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the most recent update to this booking.",
    )

    class Meta:
        ordering = ("-service_date", "-created_at")
        indexes = [
            models.Index(fields=["service_date", "city"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"Booking #{self.pk} - {self.customer.name} ({self.get_status_display()})"


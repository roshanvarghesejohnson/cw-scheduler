from django.db import models


class City(models.Model):
    """
    Represents an operational city where CycleWorks receives and handles service
    requests. Each city has a handling type which determines whether bookings
    are scheduled internally, forwarded to agencies, or handled in a hybrid mode.
    """

    class HandlingType(models.TextChoices):
        DIRECT = "DIRECT", "Direct"
        AGENCY = "AGENCY", "Agency-only"
        HYBRID = "HYBRID", "Hybrid"

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Human-readable name of the city as used by operations teams.",
    )
    handling_type = models.CharField(
        max_length=20,
        choices=HandlingType.choices,
        default=HandlingType.DIRECT,
        help_text=(
            "Determines whether CycleWorks schedules jobs internally, forwards "
            "them to an external agency, or splits them in a hybrid model."
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive cities are hidden from day-to-day scheduling operations.",
    )

    class Meta:
        verbose_name_plural = "Cities"
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.get_handling_type_display()})"


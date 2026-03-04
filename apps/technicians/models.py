from django.db import models


class Technician(models.Model):
    """
    Represents an individual technician (internal or agency) who can be assigned
    to bookings within a specific city. Daily capacity reflects how many jobs
    they can realistically complete in a working day. Base latitude/longitude
    are the starting origin for route planning; during scheduling simulation
    the current location may be updated dynamically and is not stored in the DB.
    """

    class TechnicianType(models.TextChoices):
        INTERNAL = "INTERNAL", "Internal"
        AGENCY = "AGENCY", "Agency"

    name = models.CharField(
        max_length=255,
        help_text="Full name or identifier used by operations to refer to the technician.",
    )
    technician_type = models.CharField(
        max_length=20,
        choices=TechnicianType.choices,
        default=TechnicianType.INTERNAL,
        help_text="Indicates whether the technician is an internal resource or an agency resource.",
    )
    city = models.ForeignKey(
        "cities.City",
        on_delete=models.PROTECT,
        related_name="technicians",
        help_text="Primary city in which this technician usually operates.",
    )
    base_location = models.TextField(
        help_text=(
            "Free-text description of the technician's usual starting point "
            "(e.g., neighborhood, depot address) to support routing decisions later."
        ),
    )
    is_available = models.BooleanField(
        default=True,
        help_text=(
            "Indicates whether this technician is currently available for "
            "scheduling without deactivating them or removing historical data."
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive technicians are excluded from future scheduling.",
    )
    daily_capacity = models.PositiveIntegerField(
        default=4,
        help_text="Target number of jobs this technician can handle per day.",
    )
    base_latitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Base/home latitude; starting origin for route planning.",
    )
    base_longitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Base/home longitude; starting origin for route planning.",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.get_technician_type_display()} - {self.city.name})"


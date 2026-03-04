from django.db import models


class Slot(models.Model):
    """
    Represents a 2-hour service window within a specific city. Slots act as
    containers for grouping bookings for routing and capacity planning.

    The ``current_utilization`` field is a derived cache value representing
    how many bookings are currently assigned to the slot. It should not be
    manually edited in the admin interface; it will be maintained by the
    scheduling services layer once implemented.
    """

    date = models.DateField(
        help_text="Calendar date on which this slot occurs.",
    )
    start_time = models.TimeField(
        help_text="Start time of the 2-hour service window.",
    )
    end_time = models.TimeField(
        help_text="End time of the 2-hour service window.",
    )
    city = models.ForeignKey(
        "cities.City",
        on_delete=models.PROTECT,
        related_name="slots",
        help_text="City in which this slot is scheduled.",
    )
    max_capacity = models.PositiveIntegerField(
        help_text="Maximum number of bookings that can be planned into this slot.",
    )
    current_utilization = models.PositiveIntegerField(
        default=0,
        help_text="Current count of bookings assigned to this slot.",
    )

    class Meta:
        ordering = ("date", "start_time", "city")
        unique_together = ("date", "start_time", "end_time", "city")

    def __str__(self) -> str:
        return f"{self.city.name} {self.date} {self.start_time}-{self.end_time}"


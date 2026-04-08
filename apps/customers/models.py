from django.db import models


class Customer(models.Model):
    """
    End customer requesting service. Captures basic contact details, address,
    and optional cycle information to help technicians prepare for visits.
    Latitude and longitude represent the service location used for routing
    optimization; they may be entered manually in admin.
    """

    name = models.CharField(
        max_length=255,
        help_text="Customer's full name as captured during lead intake.",
    )
    phone = models.CharField(
        max_length=50,
        help_text="Primary contact number used by operations teams for coordination.",
    )
    email = models.EmailField(
        blank=True,
        null=True,
        help_text="Optional email address for communication and notifications.",
    )
    address = models.TextField(
        help_text="Service address in free-text form as provided by the customer.",
    )
    pincode_temp = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Postal / PIN code for the service location, if provided.",
    )
    city = models.ForeignKey(
        "cities.City",
        on_delete=models.PROTECT,
        related_name="customers",
        help_text="City in which this customer resides or where service is requested.",
    )
    cycle_brand = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional brand of the customer's cycle, if known.",
    )
    cycle_model = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional model of the customer's cycle, if known.",
    )
    latitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Service location latitude for routing optimization.",
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Service location longitude for routing optimization.",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"


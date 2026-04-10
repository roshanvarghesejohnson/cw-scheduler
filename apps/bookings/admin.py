from django.contrib import admin
from django.contrib import messages

from apps.cities.models import City
from apps.routing.services.dispatch_optimizer_service import DispatchOptimizerService
from apps.routing.services.scheduling_service import SchedulingService

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "city",
        "service_date",
        "slot",
        "technician",
        "status",
        "address",
        "pincode",
        "created_at",
    )
    list_filter = ("status", "service_date", "city")
    search_fields = (
        "customer__name",
        "customer__phone",
        "customer__email",
        "notes",
    )
    autocomplete_fields = ("customer", "city", "slot", "technician")
    date_hierarchy = "service_date"
    ordering = ("-service_date", "-created_at")
    actions = ["run_daily_scheduling_action"]

    @admin.action(description="Run scheduling engine for selected bookings")
    def run_daily_scheduling_action(self, request, queryset):
        """
        Operational shortcut to run the full scheduling pipeline (slot assignment
        + technician assignment) for the city/date of the selected bookings,
        directly from Django Admin without using CLI commands.
        """
        if not queryset.exists():
            messages.warning(
                request,
                "No bookings selected. Select one or more bookings to run scheduling.",
            )
            return

        pairs = (
            queryset.values_list("city", "service_date")
            .distinct()
            .order_by("city", "service_date")
        )

        slot_service = SchedulingService()
        optimizer = DispatchOptimizerService()

        for city_id, service_date in pairs:
            city = City.objects.get(pk=city_id)
            slots_assigned = slot_service.auto_assign_slots(
                city=city, service_date=service_date
            )
            techs_assigned = optimizer.optimize(city=city, service_date=service_date)
            messages.success(
                request,
                f"{city.name} {service_date}: {slots_assigned} slots assigned, "
                f"{techs_assigned} technicians assigned.",
            )
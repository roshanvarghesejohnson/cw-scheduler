from django.contrib import admin

from .models import Technician


@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "technician_type",
        "city",
        "is_active",
        "daily_capacity",
        "base_latitude",
        "base_longitude",
    )
    list_filter = ("technician_type", "city", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("city",)
    fields = (
        "name",
        "technician_type",
        "city",
        "base_location",
        "base_latitude",
        "base_longitude",
        "is_available",
        "is_active",
        "daily_capacity",
    )


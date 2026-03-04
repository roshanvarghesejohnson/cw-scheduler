from django.contrib import admin

from .models import City


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "handling_type", "is_active")
    list_filter = ("handling_type", "is_active")
    search_fields = ("name",)
    ordering = ("name",)


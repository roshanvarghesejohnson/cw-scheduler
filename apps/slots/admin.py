from django.contrib import admin

from .models import Slot


@admin.register(Slot)
class SlotAdmin(admin.ModelAdmin):
    list_display = ("date", "start_time", "end_time", "city", "max_capacity", "current_utilization")
    list_filter = ("city", "date")
    search_fields = ("city__name",)
    ordering = ("date", "start_time")
    autocomplete_fields = ("city",)


from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "city", "email", "latitude", "longitude")
    list_filter = ("city",)
    search_fields = ("name", "phone", "email")
    autocomplete_fields = ("city",)
    fields = (
        "name",
        "phone",
        "email",
        "address",
        "city",
        "latitude",
        "longitude",
        "cycle_brand",
        "cycle_model",
    )


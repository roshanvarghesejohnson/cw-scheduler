from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0004_add_booking_service_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="address",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="pincode",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
    ]

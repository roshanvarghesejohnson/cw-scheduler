from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0002_add_booking_coordinates_and_route_position"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="crm_deal_id",
            field=models.CharField(
                max_length=64,
                null=True,
                blank=True,
                db_index=True,
                help_text="Zoho CRM Deal ID corresponding to this booking",
            ),
        ),
    ]


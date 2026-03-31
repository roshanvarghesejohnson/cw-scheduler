from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0003_add_booking_crm_deal_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="service_type",
            field=models.CharField(
                choices=[
                    ("basic", "Basic"),
                    ("standard", "Standard"),
                    ("advanced", "Advanced"),
                    ("assembly", "Assembly"),
                ],
                default="basic",
                help_text="Service tier selected at booking (e.g. basic, standard).",
                max_length=50,
            ),
        ),
    ]

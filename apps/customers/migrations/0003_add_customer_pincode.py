from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0002_add_location_coordinates"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="pincode",
            field=models.CharField(
                blank=True,
                help_text="Postal / PIN code for the service location, if provided.",
                max_length=10,
                null=True,
            ),
        ),
    ]

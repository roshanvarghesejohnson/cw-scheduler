"""
Remove 'pincode' from migration state only (0003 may be applied without the
column existing on DB). No database DDL — avoids DROP COLUMN errors.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0004_add_customer_pincode_temp"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="customer",
                    name="pincode",
                ),
            ],
            database_operations=[],
        ),
    ]

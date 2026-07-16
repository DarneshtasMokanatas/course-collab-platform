import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assignments", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="submissionversion",
            name="submitted_at",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                editable=False,
            ),
        ),
    ]

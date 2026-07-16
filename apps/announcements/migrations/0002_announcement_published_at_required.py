from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("announcements", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="announcement",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status="PUBLISHED")
                    | models.Q(published_at__isnull=False)
                ),
                name="announcement_published_at_required",
            ),
        ),
    ]

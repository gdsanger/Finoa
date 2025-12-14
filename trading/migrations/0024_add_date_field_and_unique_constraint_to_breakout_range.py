# Generated manually for issue: Erfassung Breakout Range
# Add date field and unique constraint to ensure one record per asset/phase/day

from django.db import migrations, models
from django.utils import timezone


def populate_date_field(apps, schema_editor):
    """
    Populate the date field for existing BreakoutRange records.
    Uses the start_time to derive the date.
    """
    BreakoutRange = apps.get_model('trading', 'BreakoutRange')
    
    for breakout_range in BreakoutRange.objects.all():
        # Use start_time's date in UTC
        if breakout_range.start_time:
            # Convert to UTC if needed and extract date
            if breakout_range.start_time.tzinfo is None:
                dt = timezone.make_aware(breakout_range.start_time, timezone.utc)
            else:
                dt = breakout_range.start_time.astimezone(timezone.utc)
            breakout_range.date = dt.date()
            breakout_range.save(update_fields=['date'])


class Migration(migrations.Migration):

    dependencies = [
        ('trading', '0023_tradingasset_breakout_state'),
    ]

    operations = [
        # Step 1: Add date field as nullable
        migrations.AddField(
            model_name='breakoutrange',
            name='date',
            field=models.DateField(
                db_index=True,
                help_text='Trading date (UTC) for this range',
                null=True,
                blank=True,
            ),
        ),
        # Step 2: Populate date field for existing records
        migrations.RunPython(
            populate_date_field,
            reverse_code=migrations.RunPython.noop,
        ),
        # Step 3: Make date field non-nullable
        migrations.AlterField(
            model_name='breakoutrange',
            name='date',
            field=models.DateField(
                db_index=True,
                help_text='Trading date (UTC) for this range',
            ),
        ),
        # Step 4: Add unique constraint
        migrations.AddConstraint(
            model_name='breakoutrange',
            constraint=models.UniqueConstraint(
                fields=['asset', 'phase', 'date'],
                name='unique_asset_phase_date'
            ),
        ),
    ]

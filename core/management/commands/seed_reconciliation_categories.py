"""
Management command to seed reconciliation categories.

These categories are used for balance reconciliation functionality.
"""
from django.core.management.base import BaseCommand
from core.models import Category


class Command(BaseCommand):
    help = 'Seeds reconciliation categories for balance reconciliation feature'

    def handle(self, *args, **options):
        """Create required reconciliation categories if they don't exist."""
        categories = [
            {
                'name': 'Korrektur',
                'type': None,  # Neutral, can be income or expense
            },
            {
                'name': 'Unrealisierte Gewinne/Verluste',
                'type': None,  # Neutral, can be gain or loss
            },
            {
                'name': 'RoundUp',
                'type': 'expense',  # Money leaving the account
            },
            {
                'name': 'SaveBack',
                'type': 'income',  # Money credited back
            },
        ]

        created_count = 0
        existing_count = 0

        for cat_data in categories:
            category, created = Category.objects.get_or_create(
                name=cat_data['name'],
                defaults={'type': cat_data['type']}
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Created category: {category.name}')
                )
                created_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'→ Category already exists: {category.name}')
                )
                existing_count += 1

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'Summary: {created_count} created, {existing_count} already existed'
            )
        )

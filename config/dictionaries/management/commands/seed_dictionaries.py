from django.core.management.base import BaseCommand
from django.db import transaction

from config.dictionaries.models import Country, Currency



class Command(BaseCommand):
    help = "Seed base dictionaries (currencies, countries). Safe to run multiple times."

    @transaction.atomic
    def handle(self, *args, **options):
        Currency.objects.update_or_create(
            code="EUR",
            defaults={"name": "Euro", "symbol": "€"},
        )

        Country.objects.update_or_create(
            code="SK",
            defaults={"name": "Slovakia"},
        )

        # можно добавить минимум соседей сразу:
        Country.objects.update_or_create(code="CZ", defaults={"name": "Czechia"})
        Country.objects.update_or_create(code="AT", defaults={"name": "Austria"})
        Country.objects.update_or_create(code="HU", defaults={"name": "Hungary"})
        Country.objects.update_or_create(code="PL", defaults={"name": "Poland"})

        self.stdout.write(self.style.SUCCESS("Dictionaries seeded."))

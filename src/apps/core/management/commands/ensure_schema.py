"""
Creates this app's Postgres schema (POSTGRES_SCHEMA) if it doesn't
already exist yet. This is a no-op when POSTGRES_SCHEMA isn't set
(local dev, or any deploy with its own dedicated Postgres instance
using the default "public" schema).

Exists so that multiple SiteRevive IQ tiers can share one physical
Postgres instance (e.g. Render's single free-tier database) while
keeping each tier's tables fully isolated in their own schema. Run
this before `migrate` on deploy — see the Dockerfile / Render start
command.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Creates the Postgres schema named by POSTGRES_SCHEMA, if set and not already present."

    def handle(self, *args, **options):
        schema = getattr(settings, "POSTGRES_SCHEMA", "")
        if not schema:
            self.stdout.write("POSTGRES_SCHEMA not set — skipping (using the default 'public' schema).")
            return

        with connection.cursor() as cursor:
            cursor.execute('CREATE SCHEMA IF NOT EXISTS "%s"' % schema)

        self.stdout.write(self.style.SUCCESS(f"Ensured Postgres schema '{schema}' exists."))

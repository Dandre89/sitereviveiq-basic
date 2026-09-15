"""
One-shot production boot command: ensure_schema -> migrate ->
bootstrap_admin_from_env -> collectstatic -> exec gunicorn. Exists so the
Render "Docker Command" field can be a single plain command
(`python manage.py serve`) with no shell chaining.

This matters because Render's Docker Command field execs its value as a
literal argv list — it does NOT run it through /bin/sh, so `&&`-chained
commands are not interpreted as shell operators (they show up as literal
arguments, e.g. "unrecognized arguments: && python ..."). Wrapping in
`/bin/sh -c "..."` is possible but fragile to quote correctly, and a
misquoted version can silently no-op the wrapped commands. Doing the whole
boot sequence in Python sidesteps all of that.
"""

import os

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Runs ensure_schema, migrate, bootstrap_admin_from_env, and collectstatic, then execs gunicorn."

    def handle(self, *args, **options):
        call_command("ensure_schema")
        call_command("migrate")
        call_command("bootstrap_admin_from_env")
        call_command("collectstatic", "--noinput")

        self.stdout.write(self.style.SUCCESS("Boot sequence complete — handing off to gunicorn."))

        # Replace this process with gunicorn (same as `exec gunicorn ...` in
        # a shell) so it becomes PID 1 and receives signals directly.
        os.execvp(
            "gunicorn",
            [
                "gunicorn",
                "config.wsgi:application",
                "--bind",
                "0.0.0.0:8000",
                "--workers",
                "2",
            ],
        )

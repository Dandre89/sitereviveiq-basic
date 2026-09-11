import os

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.billing.models import Subscription
from apps.workspaces.models import Workspace, WorkspaceMembership
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Idempotent, non-interactive counterpart to bootstrap_admin, meant to run
    automatically on every boot (see apps/core/management/commands/serve.py).

    This exists because Render's free plan has no shell/SSH access, so there
    is no way to run a one-off `manage.py bootstrap_admin` command after
    deploy. Reading the admin's credentials from env vars (ADMIN_EMAIL,
    ADMIN_PASSWORD, ADMIN_WORKSPACE_NAME) lets the very same boot sequence
    that runs migrate also create the first admin account, with no manual
    step required.

    Safe to leave wired into every deploy indefinitely:
      - No-ops entirely if ADMIN_EMAIL isn't set (e.g. local dev).
      - No-ops if a user with that email already exists (won't touch or
        reset an existing account's password on redeploy).
    """

    help = "Creates the first admin user + workspace from ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_WORKSPACE_NAME env vars, if not already present."

    def handle(self, *args, **options):
        email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD", "")
        workspace_name = os.environ.get("ADMIN_WORKSPACE_NAME", "").strip()

        if not email or not password or not workspace_name:
            self.stdout.write(
                "ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_WORKSPACE_NAME not fully set — skipping admin bootstrap."
            )
            return

        User = get_user_model()
        if User.objects.filter(email=email).exists():
            self.stdout.write(f"Admin user {email!r} already exists — skipping.")
            return

        with transaction.atomic():
            user = User.objects.create_superuser(email=email, password=password)
            workspace = Workspace.objects.create(name=workspace_name)
            WorkspaceMembership.objects.create(
                workspace=workspace, user=user, role=WorkspaceMembership.Role.OWNER
            )
            Subscription.objects.create(workspace=workspace)

        self.stdout.write(
            self.style.SUCCESS(
                f"Bootstrapped admin {email} and workspace {workspace_name!r} ({workspace.id})."
            )
        )

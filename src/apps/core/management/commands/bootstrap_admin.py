import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.billing.models import Subscription
from apps.workspaces.models import Workspace, WorkspaceMembership


class Command(BaseCommand):
    help = (
        "Creates the first administrator user and their workspace. "
        "Per section 13.1, there is no public registration in Build 1 — "
        "this command is the only way to create an account."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Admin email address")
        parser.add_argument("--workspace-name", required=True, help="Name for the initial workspace")
        parser.add_argument(
            "--password",
            required=False,
            help="Admin password. If omitted, you'll be prompted (recommended — avoids shell history).",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"].strip().lower()
        workspace_name = options["workspace_name"].strip()

        if User.objects.filter(email=email).exists():
            raise CommandError(f"A user with email {email!r} already exists.")

        password = options.get("password")
        if not password:
            password = getpass.getpass("Admin password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords did not match.")

        with transaction.atomic():
            user = User.objects.create_superuser(email=email, password=password)
            workspace = Workspace.objects.create(name=workspace_name)
            WorkspaceMembership.objects.create(
                workspace=workspace, user=user, role=WorkspaceMembership.Role.OWNER
            )
            # Every workspace gets a Subscription row from day one, even
            # though it starts "incomplete" (not yet linked to a real
            # Stripe customer/subscription) — an operator links it via the
            # Django admin's "Sync from Stripe" action once the deal is
            # signed. See apps.billing.middleware for how — and whether —
            # this actually blocks anything before that happens.
            Subscription.objects.create(workspace=workspace)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created admin {email} and workspace {workspace_name!r} ({workspace.id})."
            )
        )

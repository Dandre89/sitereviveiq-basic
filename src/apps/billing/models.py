import uuid

from django.db import models


class Subscription(models.Model):
    """
    One row per workspace, tracking that workspace's Stripe subscription
    state. Sales-assisted (see bootstrap_admin's docstring — there's no
    public registration), so this row starts "incomplete" — not yet
    linked to a real Stripe customer/subscription — until an operator
    links it (Django admin's "Sync from Stripe" action) after the deal
    is actually signed. From then on, apps.billing.services keeps
    status/current_period_end current via the Stripe webhook.

    SubscriptionEnforcementMiddleware reads .status off this row to
    decide whether the workspace can use the product at all — see that
    middleware for the exact rule and its "Stripe not configured in this
    environment" escape hatch (mirrors EMAIL_HOST's dev/prod split in
    config.settings.base), which is what keeps local/dev instances from
    getting locked out just because they've never been linked to Stripe.
    """

    class Status(models.TextChoices):
        # Mirrors Stripe's own Subscription.status values exactly, so
        # nothing needs translating on the way in from a webhook payload.
        INCOMPLETE = "incomplete", "Incomplete — not yet linked to Stripe"
        INCOMPLETE_EXPIRED = "incomplete_expired", "Incomplete (expired)"
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"
        UNPAID = "unpaid", "Unpaid"
        PAUSED = "paused", "Paused"

    # Statuses that mean "this workspace has paid access right now" — the
    # single source of truth the enforcement middleware checks.
    ACCESS_GRANTING_STATUSES = {Status.ACTIVE, Status.TRIALING}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="subscription"
    )

    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    stripe_price_id = models.CharField(max_length=255, blank=True)

    # Set once, at self-serve signup time (see apps.accounts.views.signup),
    # so a workspace that backs out of Checkout can be offered a "finish
    # checkout" button (billing/locked.html, checkout_cancel.html) for the
    # exact interval it originally picked, without asking again. This
    # build only ever sells Basic (no Pro/Enterprise here), so there's no
    # plan field — only which billing interval was chosen. Left blank for
    # sales-assisted rows (an operator-created workspace via
    # bootstrap_admin) — those have no self-serve checkout to resume.
    class Interval(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        ANNUAL = "annual", "Annual"

    intended_interval = models.CharField(max_length=10, choices=Interval.choices, blank=True)

    status = models.CharField(max_length=25, choices=Status.choices, default=Status.INCOMPLETE)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["stripe_customer_id"], name="billing_sub_stripe__cust_idx"),
            models.Index(fields=["stripe_subscription_id"], name="billing_sub_stripe__subs_idx"),
        ]

    def __str__(self):
        return f"{self.workspace.name} — {self.get_status_display()}"

    @property
    def has_access(self) -> bool:
        return self.status in self.ACCESS_GRANTING_STATUSES

    @property
    def is_linked(self) -> bool:
        return bool(self.stripe_customer_id and self.stripe_subscription_id)

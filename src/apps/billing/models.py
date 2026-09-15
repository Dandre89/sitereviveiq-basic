import uuid

from django.conf import settings
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

    # Set once, by apps.billing.upgrade, when this Basic workspace has been
    # migrated to a brand-new Pro account (see that module's docstring for
    # the full flow). Deliberately a SEPARATE field from `status` rather
    # than a new Status choice: `status` gets overwritten every time a
    # Stripe webhook fires for this subscription (including the
    # cancellation we trigger right after migrating), so a "migrated"
    # status value would just get clobbered back to "canceled" moments
    # later. These two fields are the only reliable, permanent record that
    # a migration happened — checked by SubscriptionEnforcementMiddleware
    # to show a "you've moved to Pro" page instead of the generic
    # "subscription inactive" one, and by apps.billing.upgrade itself as
    # the idempotency guard against running the migration twice.
    migrated_to_pro_at = models.DateTimeField(null=True, blank=True)
    migrated_to_pro_workspace_id = models.UUIDField(null=True, blank=True)

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

    @property
    def is_migrated_to_pro(self) -> bool:
        return self.migrated_to_pro_at is not None


class CreditBalance(models.Model):
    """
    One row per workspace — the spendable credit pool that replaced the
    old hard usage caps (the 1-website limit, the None/Monthly
    monitoring restriction). Every scan of any kind (manual, scheduled,
    bulk) costs exactly 1 credit — see apps.billing.credits for the
    actual spend/refund/grant logic; this model is just the current
    state. Schema is identical across all three tiers on purpose — the
    admin console's tier_basic.models mirror depends on that.

    balance vs. cycle_allotment: cycle_allotment is how many credits
    this workspace gets granted each cycle (defaults per plan — see
    apps.billing.credits.DEFAULT_CYCLE_ALLOTMENT — but a real
    overridable field). balance is use-it-or-lose-it:
    apps.billing.tasks.reset_due_credit_cycles resets it to
    cycle_allotment (not additive) whenever cycle_resets_at is reached.
    Documented assumption, flagged rather than silently picked.

    A workspace that's already migrated_to_pro (see Subscription above)
    keeps its Basic CreditBalance row around, unused — the migration
    creates a fresh one on the Pro side rather than carrying this one
    over, since Pro's own allotment is a different number.
    """

    workspace = models.OneToOneField(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="credit_balance"
    )
    balance = models.IntegerField(default=0)
    cycle_allotment = models.PositiveIntegerField(default=0)
    cycle_resets_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.workspace.name} — {self.balance}/{self.cycle_allotment} credits"

    @property
    def is_low(self) -> bool:
        """Below 20% of the cycle allotment, but not yet at zero — drives the Settings page warning pill."""
        if self.balance <= 0 or not self.cycle_allotment:
            return False
        return self.balance <= max(1, round(self.cycle_allotment * 0.2))


class CreditTransaction(models.Model):
    """
    Append-only ledger — one row per balance change. Exists specifically
    so "why does this workspace have 34 credits" is answerable by reading
    rows, not by trusting a running counter. balance_after makes each row
    self-auditing without recomputing from scratch.
    """

    class Reason(models.TextChoices):
        CYCLE_GRANT = "cycle_grant", "Monthly grant"
        SCAN_SPEND = "scan_spend", "Scan"
        SCAN_REFUND = "scan_refund", "Scan refund"
        TOPUP_PURCHASE = "topup_purchase", "Credit top-up purchase"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Manual adjustment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="credit_transactions"
    )
    delta = models.IntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    scan = models.ForeignKey(
        "scans.Scan", on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_transactions"
    )
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    balance_after = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Set for manual_adjustment rows — who in the admin console made the change.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Name kept under Postgres/Django's 30-char index-name limit
            # (models.E034) — "billing_credittx_ws_created_idx" was 31.
            models.Index(fields=["workspace", "-created_at"], name="credittx_ws_created_idx"),
        ]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.workspace.name} {sign}{self.delta} ({self.get_reason_display()})"

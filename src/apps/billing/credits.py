"""
Scan credit accounting — replaces the old hard caps (the 1-website-per-
workspace limit, and the None/Monthly monitoring-frequency restriction)
with a single spendable pool per workspace. See Credit_System_Design.md
for the full design and the reasoning behind DEFAULT_CYCLE_ALLOTMENT
below.

Every scan of any kind — manual or scheduled — costs exactly 1 credit.
apps.scans.services.start_scan is the single choke point every
scan-triggering call site goes through (the manual "run scan" button
and the scheduled-monitoring task both call it), so that's the one
place spend_credit needs wiring in — see that function for how the
transaction boundary works.

Identical logic to the Enterprise/Pro codebases' apps.billing.credits —
kept as a separate copy per tier on purpose, same as every other piece
of duplicated logic across these three independent codebases (see
Credit_System_Design.md).
"""
from django.db import transaction
from django.utils import timezone

from .models import CreditBalance, CreditTransaction

# Basic's confirmed monthly allotment (Credit_System_Design.md's table,
# confirmed as-is). Overridable per workspace via
# CreditBalance.cycle_allotment for hand-configured deals.
DEFAULT_CYCLE_ALLOTMENT = 10


class InsufficientCreditsError(Exception):
    pass


def _next_cycle_end(workspace):
    """
    Anchors a reset to the workspace's real Stripe billing period when
    it's linked; falls back to 30 days out for a workspace that isn't
    linked to Stripe yet.
    """
    subscription = getattr(workspace, "subscription", None)
    if subscription is not None and subscription.current_period_end:
        return subscription.current_period_end
    return timezone.now() + timezone.timedelta(days=30)


def get_or_create_balance(workspace) -> CreditBalance:
    """
    Read/display path — lazily creates a CreditBalance the first time a
    workspace needs one, granting a full cycle's worth immediately
    rather than starting at 0. Safe to call from a view just to render
    "X of Y credits" without spending anything.
    """
    balance, created = CreditBalance.objects.get_or_create(
        workspace=workspace,
        defaults={
            "balance": DEFAULT_CYCLE_ALLOTMENT,
            "cycle_allotment": DEFAULT_CYCLE_ALLOTMENT,
            "cycle_resets_at": _next_cycle_end(workspace),
        },
    )
    if created:
        CreditTransaction.objects.create(
            workspace=workspace,
            delta=DEFAULT_CYCLE_ALLOTMENT,
            reason=CreditTransaction.Reason.CYCLE_GRANT,
            balance_after=balance.balance,
        )
    return balance


def spend_credit(workspace, *, scan=None, amount: int = 1) -> CreditBalance:
    """
    Must be called inside a transaction.atomic() block that also creates
    (or has already created) the Scan row it's paying for — see
    apps.scans.services.start_scan — so a race between two simultaneous
    requests can't both succeed against the same last credit, and an
    InsufficientCreditsError here rolls back the Scan creation too
    rather than leaving an orphan QUEUED row with no credit behind it.
    select_for_update() requires an enclosing atomic block, which is
    exactly what start_scan provides — this function deliberately does
    not open its own.
    """
    balance, _ = CreditBalance.objects.select_for_update().get_or_create(
        workspace=workspace,
        defaults={
            "balance": DEFAULT_CYCLE_ALLOTMENT,
            "cycle_allotment": DEFAULT_CYCLE_ALLOTMENT,
            "cycle_resets_at": _next_cycle_end(workspace),
        },
    )
    if balance.balance < amount:
        raise InsufficientCreditsError(
            f"Workspace {workspace.id} has {balance.balance} credit(s), needs {amount}."
        )
    balance.balance -= amount
    balance.save(update_fields=["balance", "updated_at"])
    CreditTransaction.objects.create(
        workspace=workspace,
        delta=-amount,
        reason=CreditTransaction.Reason.SCAN_SPEND,
        scan=scan,
        balance_after=balance.balance,
    )
    return balance


def refund_credit(scan, *, amount: int = 1) -> None:
    """
    Called from apps.scans.services.execute_scan for every path that
    sets Scan.Status.FAILED — a failure isn't the customer's fault
    (target site down, timed out, blocked the crawler, or the website
    was archived out from under the scan). Deliberately NOT called for
    a customer-initiated cancellation — a scan the customer backs out of
    themselves still spent the credit, per Credit_System_Design.md
    Section 1.
    """
    workspace = scan.workspace
    with transaction.atomic():
        balance = CreditBalance.objects.select_for_update().get(workspace=workspace)
        balance.balance += amount
        balance.save(update_fields=["balance", "updated_at"])
        CreditTransaction.objects.create(
            workspace=workspace,
            delta=amount,
            reason=CreditTransaction.Reason.SCAN_REFUND,
            scan=scan,
            balance_after=balance.balance,
        )


def add_credits(
    workspace, amount: int, *, reason: str, stripe_payment_intent_id: str = "", created_by=None
) -> CreditBalance:
    """
    Shared entry point for both real money (the self-serve Stripe top-up
    webhook) and an operator's manual adjustment in the admin console —
    same ledger, same balance update, just a different `reason` and, for
    a manual adjustment, a `created_by` so it's attributable.
    """
    with transaction.atomic():
        balance, _ = CreditBalance.objects.select_for_update().get_or_create(
            workspace=workspace,
            defaults={
                "balance": 0,
                "cycle_allotment": DEFAULT_CYCLE_ALLOTMENT,
                "cycle_resets_at": _next_cycle_end(workspace),
            },
        )
        balance.balance += amount
        balance.save(update_fields=["balance", "updated_at"])
        CreditTransaction.objects.create(
            workspace=workspace,
            delta=amount,
            reason=reason,
            stripe_payment_intent_id=stripe_payment_intent_id,
            balance_after=balance.balance,
            created_by=created_by,
        )
    return balance


def reset_due_cycles() -> int:
    """
    Called by a daily Celery Beat task (apps.billing.tasks). Use-it-or-
    lose-it: resets balance to cycle_allotment (not additive) for every
    workspace whose cycle_resets_at has passed, then advances
    cycle_resets_at to the workspace's current Stripe period end if
    linked, else +30 days. Returns how many workspaces were reset.
    """
    due_ids = list(
        CreditBalance.objects.filter(cycle_resets_at__lte=timezone.now()).values_list("pk", flat=True)
    )
    reset_count = 0
    for pk in due_ids:
        with transaction.atomic():
            balance = CreditBalance.objects.select_for_update().select_related(
                "workspace__subscription"
            ).get(pk=pk)
            # Re-check under the lock — cycle_resets_at could have moved
            # between the list query above and this row's turn.
            if balance.cycle_resets_at > timezone.now():
                continue
            delta = balance.cycle_allotment - balance.balance
            balance.balance = balance.cycle_allotment
            balance.cycle_resets_at = _next_cycle_end(balance.workspace)
            balance.save(update_fields=["balance", "cycle_resets_at", "updated_at"])
            CreditTransaction.objects.create(
                workspace=balance.workspace,
                delta=delta,
                reason=CreditTransaction.Reason.CYCLE_GRANT,
                balance_after=balance.balance,
            )
        reset_count += 1
    return reset_count

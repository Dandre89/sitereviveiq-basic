from django.contrib import admin, messages

from . import services
from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """
    The sales-assisted linking workflow lives here: after a deal is
    signed and an operator creates the customer + subscription directly
    in the Stripe Dashboard, paste those two IDs into a workspace's row
    below and run "Sync from Stripe" to pull in the real status, renewal
    date, and price — see apps.billing.services for what that call does.
    """

    list_display = [
        "workspace", "status", "is_linked", "current_period_end", "cancel_at_period_end", "updated_at",
    ]
    list_filter = ["status", "cancel_at_period_end"]
    search_fields = ["workspace__name", "stripe_customer_id", "stripe_subscription_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["workspace"]
    actions = ["sync_from_stripe"]

    @admin.display(boolean=True, description="Linked to Stripe")
    def is_linked(self, obj):
        return obj.is_linked

    @admin.action(description="Sync selected subscriptions from Stripe")
    def sync_from_stripe(self, request, queryset):
        synced, failed = 0, 0
        for subscription in queryset:
            if not subscription.stripe_subscription_id:
                failed += 1
                continue
            try:
                services.sync_subscription_from_stripe(subscription)
                synced += 1
            except services.StripeNotConfiguredError:
                self.message_user(
                    request, "STRIPE_SECRET_KEY isn't set in this environment.", level=messages.ERROR
                )
                return
            except Exception as exc:  # noqa: BLE001 — surface whatever Stripe/network error occurred
                failed += 1
                self.message_user(
                    request, f"{subscription.workspace}: {exc}", level=messages.WARNING
                )

        if synced:
            self.message_user(request, f"Synced {synced} subscription(s) from Stripe.", level=messages.SUCCESS)
        if failed:
            self.message_user(
                request,
                f"{failed} subscription(s) couldn't be synced — check they have a "
                "stripe_subscription_id set.",
                level=messages.WARNING,
            )

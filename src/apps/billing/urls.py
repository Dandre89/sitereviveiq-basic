from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("pricing/", views.pricing, name="pricing"),
    path("checkout/success/", views.checkout_success, name="checkout_success"),
    path("checkout/cancel/", views.checkout_cancel, name="checkout_cancel"),
    path("checkout/retry/", views.retry_checkout, name="retry_checkout"),
    path("upgrade/", views.upgrade_to_pro, name="upgrade_to_pro"),
    path("credits/buy/", views.buy_credits, name="buy_credits"),
    path("credits/topup-success/", views.topup_success, name="topup_success"),
    path("portal/", views.billing_portal, name="portal"),
    path("webhook/", views.stripe_webhook, name="webhook"),
]

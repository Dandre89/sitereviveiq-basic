from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("pricing/", views.pricing, name="pricing"),
    path("checkout/success/", views.checkout_success, name="checkout_success"),
    path("checkout/cancel/", views.checkout_cancel, name="checkout_cancel"),
    path("checkout/retry/", views.retry_checkout, name="retry_checkout"),
    path("portal/", views.billing_portal, name="portal"),
    path("webhook/", views.stripe_webhook, name="webhook"),
]

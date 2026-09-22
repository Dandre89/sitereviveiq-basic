from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django_ratelimit.decorators import ratelimit

from . import views

app_name = "accounts"

# Rate limits on the public, unauthenticated auth endpoints — brute-force
# login guessing, password-reset-email spam/enumeration, and automated
# signup abuse. Keyed by IP; block=True means a request past the limit is
# routed to settings.RATELIMIT_VIEW (429.html) instead of reaching the
# view at all.
signup_view = ratelimit(key="ip", rate="10/h", method="POST", block=True)(views.signup)
login_view = ratelimit(key="ip", rate="10/5m", method="POST", block=True)(
    auth_views.LoginView.as_view(template_name="registration/login.html", redirect_authenticated_user=True)
)
password_reset_view = ratelimit(key="ip", rate="5/h", method="POST", block=True)(
    auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        email_template_name="registration/password_reset_email.txt",
        html_email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
    )
)

urlpatterns = [
    path("signup/", signup_view, name="signup"),
    path(
        "login/",
        login_view,
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.update_profile, name="update_profile"),
    path("password/", views.change_password, name="change_password"),
    path("notifications/", views.update_my_notification_preferences, name="update_my_notification_preferences"),
    path("delete/", views.request_account_deletion, name="request_account_deletion"),
    # Self-service "forgot password" flow — added alongside the internal
    # admin console's own password-reset trigger (see
    # views.internal_trigger_password_reset below), both built on the
    # same underlying Django auth token mechanism so a link minted by
    # either path validates the same way.
    path(
        "password-reset/",
        password_reset_view,
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.PasswordChangedConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path(
        "internal/trigger-password-reset/",
        views.internal_trigger_password_reset,
        name="internal_trigger_password_reset",
    ),
]

"""
Shared helper for every triggered/transactional email the app sends
(welcome, password-changed confirmation, scan/monitoring notifications,
etc.) — anything customer-facing beyond Django's own built-in
password-reset flow (which has its own template wiring in
apps/accounts/urls.py).

Renders a branded HTML template (templates/emails/<name>.html, extending
templates/emails/base_email.html) plus a plain-text fallback rendered
from the same context, and sends both via EmailMultiAlternatives so
mail clients that block HTML — and spam filters that penalize HTML-only
mail — still get a readable message.

A plain-text template is optional: if templates/emails/<name>.txt
doesn't exist, the HTML is stripped of tags as a reasonable fallback
rather than failing to send.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def send_admin_notification(*, subject: str, body: str) -> bool:
    """
    Plain-text internal alert to the team inbox (settings.ADMIN_NOTIFICATION_EMAIL)
    for things worth an immediate heads-up  currently just the two
    new-signup pings in apps.accounts.views.signup and
    apps.billing.services.link_subscription_from_checkout_session.
    Deliberately NOT templated/branded like send_templated_email below:
    this is an internal alert to us, not a customer-facing email, so it
    skips the HTML+branding machinery entirely. Same "never break the
    caller's request" rationale as send_templated_email  a failed
    internal alert must never surface as an error to a signing-up
    customer.
    """
    to = settings.ADMIN_NOTIFICATION_EMAIL
    if not to:
        return False
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
        return True
    except Exception:  # noqa: BLE001  see docstring
        return False


def send_templated_email(*, template_name: str, context: dict, subject: str, to: list[str], fail_silently: bool = True) -> bool:
    """
    template_name: base name under templates/emails/, e.g. "welcome" for
    templates/emails/welcome.html (+ optional welcome.txt).
    """
    if not to:
        return False

    html_body = render_to_string(f"emails/{template_name}.html", context)
    try:
        text_body = render_to_string(f"emails/{template_name}.txt", context)
    except TemplateDoesNotExist:
        text_body = strip_tags(html_body)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
    )
    message.attach_alternative(html_body, "text/html")
    try:
        message.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001 — a transactional email failing must never break the caller's request
        if not fail_silently:
            raise
        return False

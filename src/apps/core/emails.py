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
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils.html import strip_tags


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

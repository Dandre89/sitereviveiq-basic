from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from xhtml2pdf import pisa

from apps.websites.models import Website
from apps.workspaces.access import require_can_edit, require_website_access, scope_websites

from .models import Report, ReportShareLink
from .services import (
    generate_prospect_audit,
    get_or_create_report_share_link,
    record_share_link_view,
    revoke_report_share_links,
)


def _safe_redirect(request, fallback_url):
    """
    Deletes happen from several places (the overview list, a website's
    own Reports page, the detail page itself) so a hardcoded redirect
    target would bounce the agency somewhere unexpected. Honors a
    same-origin `next` from the submitting form and falls back to
    `fallback_url` otherwise — same allowed-host check Django's own
    LoginView uses for its `next` param.
    """
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect(fallback_url)


def _render_report_pdf(report):
    html = render_to_string("reports/report_pdf.html", {"report": report})
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        return None
    filename = f"{report.website.normalized_host or report.website.name}-{report.report_type}.pdf".replace(" ", "-")
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def report_overview(request):
    reports = scope_websites(
        request, Report.objects.filter(workspace=request.workspace).select_related("website")
    )

    website_id = request.GET.get("website", "")
    if website_id:
        reports = reports.filter(website_id=website_id)

    report_sort = request.GET.get("rsort", "newest")
    reports = reports.order_by("generated_at" if report_sort == "oldest" else "-generated_at")

    return render(
        request,
        "reports/overview.html",
        {
            "reports": reports,
            "websites": scope_websites(
                request, Website.objects.filter(workspace=request.workspace), lookup="pk"
            ).order_by("name"),
            "selected_website": website_id,
            "selected_report_sort": report_sort,
        },
    )


@login_required
def report_list(request, website_pk):
    website = get_object_or_404(Website, pk=website_pk, workspace=request.workspace)
    require_website_access(request, website.pk)

    reports = website.reports.all()
    report_sort = request.GET.get("rsort", "newest")
    reports = reports.order_by("generated_at" if report_sort == "oldest" else "-generated_at")

    can_generate_audit = website.last_scan is not None
    return render(
        request,
        "reports/list.html",
        {
            "website": website,
            "reports": reports,
            "selected_report_sort": report_sort,
            "can_generate_audit": can_generate_audit,
        },
    )


@login_required
@require_can_edit
def generate_report(request, website_pk):
    website = get_object_or_404(Website, pk=website_pk, workspace=request.workspace)
    require_website_access(request, website.pk)
    if request.method != "POST":
        return redirect("reports:list", website_pk=website.pk)

    # Basic only ever generates a Prospect Audit — Client Health and
    # Renovation Results reports need an active baseline to compare
    # against, and Baselines is a Pro+ feature not present in this build.
    if not website.last_scan:
        messages.error(request, "This website needs a completed scan first.")
        return redirect("reports:list", website_pk=website.pk)
    report = generate_prospect_audit(website, website.last_scan, generated_by=request.user)

    messages.success(request, f"Generated {report.get_report_type_display()}.")
    return redirect("reports:detail", pk=report.pk)


@login_required
def report_detail(request, pk):
    report = get_object_or_404(Report, pk=pk, workspace=request.workspace)
    require_website_access(request, report.website_id)
    return render(request, "reports/detail.html", {"report": report})


@login_required
@require_can_edit
def report_delete(request, pk):
    report = get_object_or_404(Report, pk=pk, workspace=request.workspace)
    require_website_access(request, report.website_id)
    website_pk = report.website_id
    if request.method == "POST":
        report.delete()
        messages.success(request, "Report deleted.")
        return _safe_redirect(request, reverse("reports:list", args=[website_pk]))
    return redirect("reports:detail", pk=report.pk)


@login_required
@require_can_edit
def report_client_view(request, pk):
    """
    Staff-side preview of the report, plus the real public share link a
    client can open with no login — generated (or reused, if a valid one
    already exists) on every visit to this page.
    """
    report = get_object_or_404(Report, pk=pk, workspace=request.workspace)
    require_website_access(request, report.website_id)
    share_link = get_or_create_report_share_link(report, created_by=request.user)
    public_url = request.build_absolute_uri(
        "/reports/share/r/{}/".format(share_link.token)
    )
    return render(
        request,
        "reports/client_view.html",
        {"report": report, "hide_chrome": True, "share_link": share_link, "public_url": public_url},
    )


@login_required
@require_can_edit
def report_revoke_share_link(request, pk):
    report = get_object_or_404(Report, pk=pk, workspace=request.workspace)
    require_website_access(request, report.website_id)
    if request.method == "POST":
        revoke_report_share_links(report)
        messages.success(request, "Share link revoked. The old link no longer works — a new one was generated.")
    return redirect("reports:client_view", pk=report.pk)


def report_public_view(request, token):
    """
    The real client-facing page — no login, no workspace scoping, just
    the token. This is what the "Copy client link" button on
    report_client_view actually hands out.
    """
    share_link = get_object_or_404(ReportShareLink, token=token)
    if not share_link.is_valid():
        return render(request, "reports/share_link_invalid.html", {"hide_chrome": True}, status=410)

    record_share_link_view(share_link)
    return render(
        request,
        "reports/public_report.html",
        {"report": share_link.report, "hide_chrome": True, "share_token": share_link.token},
    )


@login_required
def report_export_pdf(request, pk):
    report = get_object_or_404(Report, pk=pk, workspace=request.workspace)
    require_website_access(request, report.website_id)
    response = _render_report_pdf(report)
    if response is None:
        messages.error(request, "Could not generate the PDF. Please try again.")
        return redirect("reports:detail", pk=report.pk)
    return response


def report_public_pdf(request, token):
    """Lets an anonymous client holding a valid share link download the PDF too."""
    share_link = get_object_or_404(ReportShareLink, token=token)
    if not share_link.is_valid():
        return render(request, "reports/share_link_invalid.html", {"hide_chrome": True}, status=410)

    response = _render_report_pdf(share_link.report)
    if response is None:
        return HttpResponse("Could not generate the PDF. Please try again.", status=500)
    return response

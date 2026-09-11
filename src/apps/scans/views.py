from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.workspaces.access import require_website_access

from .models import Scan


@login_required
def scan_progress(request, pk):
    scan = get_object_or_404(Scan.objects.select_related("website"), pk=pk, workspace=request.workspace)
    # Competitor scans are keyed to a competitor Website row, which isn't
    # itself in anyone's WebsiteAccess set — access follows the primary
    # site it's tracked against instead (same rule as monitoring.views).
    require_website_access(request, scan.website.tracks_competitor_for_id or scan.website_id)
    events = scan.events.order_by("-created_at")[:100]
    template = "scans/_progress_fragment.html" if request.htmx else "scans/progress.html"
    return render(request, template, {"scan": scan, "events": events})

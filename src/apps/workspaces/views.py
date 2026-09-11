from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import WorkspaceGeneralForm, WorkspaceNotificationsForm
from .models import WorkspaceMembership


@login_required
def team_list(request):
    """
    Basic is single-user by design (no invites, no roles, no per-member
    management) — this just shows the current account as the sole
    workspace member, for consistency with the "Team" nav item other
    tiers have. There's nothing to invite, promote, or remove here.
    """
    membership = WorkspaceMembership.objects.filter(
        workspace=request.workspace, user=request.user
    ).select_related("user").first()

    return render(
        request,
        "workspaces/team.html",
        {"membership": membership},
    )


@login_required
def workspace_update_general(request):
    if request.method != "POST":
        return redirect("core:settings")

    form = WorkspaceGeneralForm(request.POST, instance=request.workspace)
    if form.is_valid():
        form.save()
        messages.success(request, "Workspace updated.")
    else:
        messages.error(request, "Couldn't save that — check the form and try again.")
    return redirect("core:settings")


@login_required
def workspace_update_notifications(request):
    if request.method != "POST":
        return redirect("core:settings")

    form = WorkspaceNotificationsForm(request.POST, instance=request.workspace)
    if form.is_valid():
        form.save()
        messages.success(request, "Notification preferences updated.")
    else:
        messages.error(request, "Couldn't save that — check the form and try again.")
    return redirect("core:settings")

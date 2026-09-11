from django import forms

from .models import Workspace


class WorkspaceGeneralForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ["name"]


class WorkspaceNotificationsForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = [
            "notify_critical_findings",
            "notify_score_drops",
            "notify_scan_completed",
            "notify_new_opportunities",
            "notify_returning_issues",
            "score_drop_threshold",
        ]
        widgets = {
            "score_drop_threshold": forms.NumberInput(attrs={"min": 1, "max": 100, "style": "max-width:100px;"}),
        }

    def clean_score_drop_threshold(self):
        value = self.cleaned_data["score_drop_threshold"]
        if value < 1:
            raise forms.ValidationError("Threshold must be at least 1 point.")
        return value

from urllib.parse import urlsplit

from django import forms

from scanner.normalizer import normalize_url

from .models import Website


class WebsiteForm(forms.ModelForm):
    class Meta:
        model = Website
        fields = ["name", "submitted_url", "website_type", "max_pages", "max_depth"]
        widgets = {
            "submitted_url": forms.URLInput(attrs={"placeholder": "https://example.com"}),
            "website_type": forms.RadioSelect,
        }

    def clean_submitted_url(self):
        url = self.cleaned_data["submitted_url"]
        normalized = normalize_url(url)
        if not normalized:
            raise forms.ValidationError("Enter a valid http(s) URL.")
        return normalized

    def clean_max_pages(self):
        value = self.cleaned_data["max_pages"]
        if not (1 <= value <= 500):
            raise forms.ValidationError("Max pages must be between 1 and 500.")
        return value

    def clean_max_depth(self):
        value = self.cleaned_data["max_depth"]
        if not (1 <= value <= 10):
            raise forms.ValidationError("Max depth must be between 1 and 10.")
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.normalized_host = (urlsplit(instance.submitted_url).hostname or "").lower()
        instance.canonical_url = instance.submitted_url
        if commit:
            instance.save()
        return instance

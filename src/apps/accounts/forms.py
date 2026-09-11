from django import forms
from django.contrib.auth import password_validation

from .models import User


class SignupForm(forms.Form):
    """
    Self-serve signup — this build only ever sells Basic (see
    apps.accounts.views.signup). Deliberately a plain Form, not a
    ModelForm: it creates a User AND a Workspace AND a Subscription
    together in one transaction, which doesn't map cleanly onto any
    single model.
    """

    full_name = forms.CharField(max_length=150, label="Full name")
    email = forms.EmailField(label="Email")
    workspace_name = forms.CharField(max_length=255, label="Agency / company name")
    password = forms.CharField(widget=forms.PasswordInput, label="Password")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists — log in instead.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        password_validation.validate_password(password)
        return password


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.exclude(pk=self.instance.pk).filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserManager(BaseUserManager):
    """Custom manager — email is the unique login identifier, no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Matches the User table in section 10 of the spec: UUID pk, email is the
    unique login identifier, no separate username.
    """

    username = None
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email


class UserNotificationPreference(models.Model):
    """
    One row per user, created lazily via get_for_user() the first time
    it's needed (settings page render, or a notification send check) —
    every user is assumed opted-in to everything until they say
    otherwise, so a missing row behaves exactly like a row of all-True.

    This is a per-user layer on top of the existing per-workspace toggles
    (Workspace.notify_* in apps.workspaces.models): a monitoring email
    only goes out if BOTH the workspace has that category turned on AND
    the specific recipient hasn't opted out personally. Security and
    account emails (password reset/changed, welcome, account deletion)
    are never gated by this — they're not listed here on purpose.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_preference")

    notify_critical_findings = models.BooleanField(default=True)
    notify_score_drops = models.BooleanField(default=True)
    notify_scan_completed = models.BooleanField(default=True)
    notify_new_opportunities = models.BooleanField(default=True)
    notify_returning_issues = models.BooleanField(default=True)
    notify_credits_exhausted = models.BooleanField(default=True)
    notify_proposal_response = models.BooleanField(default=True)

    def __str__(self):
        return f"Notification preferences for {self.user}"

    @classmethod
    def get_for_user(cls, user):
        pref, _ = cls.objects.get_or_create(user=user)
        return pref

    @classmethod
    def wants(cls, user, field_name: str) -> bool:
        """True if `user` is None (no specific recipient to check), the
        field doesn't exist (fail open rather than silently drop a
        legitimate email over a typo), or the user's own preference row
        has that category on — false only on an explicit opt-out."""
        if user is None:
            return True
        pref = cls.objects.filter(user=user).only(field_name).first()
        if pref is None:
            return True
        return getattr(pref, field_name, True)

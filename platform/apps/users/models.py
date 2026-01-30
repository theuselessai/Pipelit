import uuid

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    telegram_user_id = models.BigIntegerField(unique=True, null=True, blank=True)
    github_username = models.CharField(max_length=255, blank=True, default="")
    gitlab_username = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} (tg:{self.telegram_user_id})"


class APIKey(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_key",
    )
    key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"APIKey for {self.user.username}"

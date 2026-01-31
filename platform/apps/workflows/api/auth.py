from django.http import HttpRequest
from ninja.security import HttpBearer

from apps.users.models import APIKey, UserProfile


class BearerAuth(HttpBearer):
    """Bearer token auth using APIKey, returns UserProfile."""

    def authenticate(self, request: HttpRequest, token: str):
        try:
            api_key = APIKey.objects.select_related("user__profile").get(key=token)
        except (APIKey.DoesNotExist, ValueError):
            return None
        profile, _ = UserProfile.objects.get_or_create(user=api_key.user)
        return profile

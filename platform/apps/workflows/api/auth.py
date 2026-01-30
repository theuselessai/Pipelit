from django.http import HttpRequest
from ninja.security import HttpBearer, APIKeyCookie
from django.conf import settings

from apps.users.models import APIKey, UserProfile


class SessionAuth(APIKeyCookie):
    """Django session-based auth that returns UserProfile."""

    param_name: str = settings.SESSION_COOKIE_NAME

    def authenticate(self, request: HttpRequest, key):
        if request.user.is_authenticated:
            try:
                return request.user.profile
            except UserProfile.DoesNotExist:
                return None
        return None


class BearerAuth(HttpBearer):
    """Bearer token auth using APIKey, returns UserProfile."""

    def authenticate(self, request: HttpRequest, token: str):
        try:
            api_key = APIKey.objects.select_related("user__profile").get(key=token)
        except (APIKey.DoesNotExist, ValueError):
            return None
        profile, _ = UserProfile.objects.get_or_create(user=api_key.user)
        return profile


# django-ninja accepts a list of auth backends; first match wins
SessionOrBasicAuth = [SessionAuth(), BearerAuth()]

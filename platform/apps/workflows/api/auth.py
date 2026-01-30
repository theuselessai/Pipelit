from django.contrib.auth import authenticate
from django.http import HttpRequest
from ninja.security import HttpBasicAuth, APIKeyCookie
from django.conf import settings

from apps.users.models import UserProfile


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


class BasicAuthBackend(HttpBasicAuth):
    """HTTP Basic auth that returns UserProfile."""

    def authenticate(self, request: HttpRequest, username: str, password: str):
        user = authenticate(request, username=username, password=password)
        if user:
            try:
                return user.profile
            except UserProfile.DoesNotExist:
                return None
        return None


# django-ninja accepts a list of auth backends; first match wins
SessionOrBasicAuth = [SessionAuth(), BasicAuthBackend()]

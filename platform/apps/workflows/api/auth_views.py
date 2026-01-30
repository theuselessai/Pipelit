import uuid

from django.contrib.auth import authenticate
from ninja import Router, Schema

from apps.users.models import APIKey

router = Router(tags=["auth"])


class TokenRequest(Schema):
    username: str
    password: str


class TokenResponse(Schema):
    key: str


@router.post("/token/", response={200: TokenResponse, 401: dict}, auth=None)
def obtain_token(request, payload: TokenRequest):
    user = authenticate(request, username=payload.username, password=payload.password)
    if not user:
        return 401, {"detail": "Invalid credentials."}
    api_key, created = APIKey.objects.get_or_create(user=user)
    if not created:
        api_key.key = uuid.uuid4()
        api_key.save(update_fields=["key"])
    return 200, {"key": str(api_key.key)}
